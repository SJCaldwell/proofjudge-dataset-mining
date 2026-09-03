// Blind adjudication of proof pairs.
//
// Run with the Claude Code Workflow tool. It fans out over the batches written
// by `proofjudge evalset emit-tasks`; each agent judges ~12 blinded pairs and
// writes its verdicts to disk. Running it as a Workflow (rather than direct API
// calls) bills a Claude subscription rather than API credits.
//
//   Workflow({
//     scriptPath: "workflows/blind_adjudication.js",
//     args: { dir: "<abs path to data/evalset>", nBatches: 36, prefix: "blind" }
//   })
//
// nBatches must equal the batch count printed by emit-tasks.

export const meta = {
  name: 'blind-proof-adjudication',
  description: 'Blind, order-balanced adjudication of Lean proof pairs to verify eval-set labels',
  phases: [{ title: 'Adjudicate', detail: 'one agent per batch of blinded pairs' }],
}

const DIR = args.dir
const N = args.nBatches
const PREFIX = args.prefix || 'blind'

phase('Adjudicate')

const SCHEMA = {
  type: 'object',
  properties: {
    verdicts: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          task_id: { type: 'string' },
          key_difference: { type: 'string', description: 'One sentence: what actually differs between the two proofs.' },
          verdict: { type: 'string', enum: ['A', 'B', 'comparable'] },
          reasoning: { type: 'string', description: '2-4 sentences justifying the verdict in Mathlib review terms.' },
          confidence: { type: 'string', enum: ['low', 'medium', 'high'] },
        },
        required: ['task_id', 'key_difference', 'verdict', 'reasoning', 'confidence'],
        additionalProperties: false,
      },
    },
    n_judged: { type: 'integer' },
    outfile: { type: 'string' },
  },
  required: ['verdicts', 'n_judged', 'outfile'],
  additionalProperties: false,
}

function promptFor(i) {
  return `You are an experienced Mathlib maintainer reviewing Lean 4 proof quality.

## Setup

1. Read the calibration examples at ${DIR}/anchors.md — read the WHOLE file, including the section at the end about what the examples do and do not tell you.
2. Read ${DIR}/${PREFIX}_batches.json and take element ${i} of that array. It is a list of task_id strings — YOUR assignment.
3. Read ${DIR}/${PREFIX}_tasks.jsonl. Each line has task_id, declaration, file_path, proof_a, proof_b. Find the lines whose task_id is in your assignment.

## Your task

For each assigned task_id, decide which of the two proofs is the better piece of Mathlib: "A", "B", or "comparable".

## Critical constraints

- You are NOT told which proof came first, which Mathlib accepted, or which a reviewer preferred. The file deliberately carries no such information. Do not try to infer it. Do not assume Proof B is the improvement — the order was assigned by a coin flip balanced across the whole study.
- Judge each pair INDEPENDENTLY. Do not let a run of similar verdicts pull the next one. There is no quota and no expected distribution of answers.
- Do not read any other file in that directory. Several contain the answers; opening them invalidates the study. You need exactly the three files named above.

## What makes a proof better Mathlib

- Leverages existing library API rather than reconstructing it by hand
- Uses automation proportionate to the goal (not a sledgehammer, not a manual grind)
- Has structure that reveals the mathematical argument
- Is robust rather than dependent on incidental goal state or fragile term ordering
- Is readable by someone who did not write it

Length is evidence, not a criterion. A shorter proof is often better because it leans on the right lemma; it is not better merely for being shorter. A longer proof that names its intermediate steps can beat a terse one that obscures them.

## Verdict

Answer "A" or "B" only when one is genuinely the better contribution. Answer "comparable" when the difference is stylistic, mechanical, cosmetic, or a real toss-up — do not force a choice you would not defend in review. "comparable" is a legitimate and expected answer.

## Output

Write your verdicts as JSON to ${DIR}/${PREFIX}_verdicts_${i}.json in the form {"verdicts": [...]} with one entry per assigned task_id, then return the same verdicts in your structured output. Set outfile to the path you wrote and n_judged to the number of verdicts.

Judge every assigned task. Do not skip any.`
}

const results = await parallel(
  Array.from({ length: N }, (_, i) => () =>
    agent(promptFor(i), { label: `adjudicate:batch${i}`, phase: 'Adjudicate', schema: SCHEMA })
  )
)

const ok = results.filter(Boolean)
const total = ok.reduce((s, r) => s + (r.n_judged || 0), 0)
log(`adjudication complete: ${ok.length}/${N} batches, ${total} verdicts`)

const tally = {}
for (const r of ok) for (const v of r.verdicts || []) tally[v.verdict] = (tally[v.verdict] || 0) + 1

return {
  batches_ok: ok.length,
  batches_failed: N - ok.length,
  total_verdicts: total,
  raw_verdict_tally: tally,
  failed_batches: Array.from({ length: N }, (_, i) => i).filter((i) => !results[i]),
}
