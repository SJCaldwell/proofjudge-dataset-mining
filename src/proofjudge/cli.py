"""CLI entry point for the ProofJudge dataset mining pipeline."""

import asyncio
import logging
import sys

import typer
from rich.console import Console
from rich.table import Table

from proofjudge.config import Settings
from proofjudge.github.client import GitHubClient
from proofjudge.storage.database import Database

app = typer.Typer(
    name="proofjudge",
    help="Mine mathlib4 PRs for proof quality triplets.",
)
console = Console()


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def _get_settings() -> Settings:
    try:
        return Settings()  # type: ignore[call-arg]
    except Exception as e:
        console.print(f"[red]Configuration error:[/red] {e}")
        console.print("Make sure .env file exists with GITHUB_TOKEN set.")
        raise typer.Exit(code=1) from e


@app.command()
def discover(
    full_scan: bool = typer.Option(True, help="Run full GraphQL scan of all closed PRs"),
    keywords: bool = typer.Option(True, help="Run keyword searches"),
    scan_limit: int | None = typer.Option(None, help="Limit number of PRs in full scan"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Phase 1+2: Discover and enrich candidate PR numbers."""
    _setup_logging(verbose)
    settings = _get_settings()

    async def _run() -> None:
        from proofjudge.pipeline.discovery import run_discovery
        from proofjudge.pipeline.enrichment import run_enrichment

        db = Database(settings.db_path)
        async with GitHubClient(settings.github_token) as client:
            await run_discovery(
                client,
                db,
                settings,
                full_scan=full_scan,
                keywords=keywords,
                scan_limit=scan_limit,
            )

            # Enrich any keyword-found PRs not covered by the scan
            await run_enrichment(client, db, settings)

        db.close()

    asyncio.run(_run())
    console.print("[green]Discovery complete.[/green]")
    status()


@app.command()
def enrich(
    limit: int | None = typer.Option(None, help="Limit number of PRs to enrich"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Phase 2: Enrich PRs discovered via keyword search with full metadata."""
    _setup_logging(verbose)
    settings = _get_settings()

    async def _run() -> None:
        from proofjudge.pipeline.enrichment import run_enrichment

        db = Database(settings.db_path)
        async with GitHubClient(settings.github_token) as client:
            count = await run_enrichment(client, db, settings, limit=limit)
            console.print(f"Enriched {count} PRs.")
        db.close()

    asyncio.run(_run())


@app.command()
def extract(
    limit: int | None = typer.Option(None, help="Max PRs to extract"),
    concurrency: int = typer.Option(3, help="Concurrent extraction workers"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Phase 3: Deep extraction of reviews, comments, commits, and diffs."""
    _setup_logging(verbose)
    settings = _get_settings()

    async def _run() -> None:
        from proofjudge.pipeline.extraction import run_extraction

        db = Database(settings.db_path)
        async with GitHubClient(settings.github_token) as client:
            count = await run_extraction(client, db, settings, limit=limit, concurrency=concurrency)
            console.print(f"Extracted {count} PRs.")
        db.close()

    asyncio.run(_run())


@app.command(name="parse")
def parse_cmd(
    limit: int | None = typer.Option(None, help="Max PRs to parse"),
    concurrency: int = typer.Option(3, help="Concurrent parsing workers"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Phase 4: Parse proof blocks and match initial/final pairs."""
    _setup_logging(verbose)
    settings = _get_settings()

    async def _run() -> None:
        from proofjudge.pipeline.parsing import run_parsing

        db = Database(settings.db_path)
        async with GitHubClient(settings.github_token) as client:
            count = await run_parsing(
                client, db, settings, limit=limit, concurrency=concurrency
            )
            console.print(f"Parsed {count} PRs.")
        db.close()

    asyncio.run(_run())


@app.command()
def summarize(
    limit: int | None = typer.Option(None, help="Max PRs to summarize"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Phase 5: Classify and summarize proof pairs via Claude."""
    _setup_logging(verbose)
    settings = _get_settings()

    if not settings.anthropic_api_key:
        console.print("[red]Error:[/red] ANTHROPIC_API_KEY not set in .env")
        raise typer.Exit(code=1)

    async def _run() -> None:
        from proofjudge.pipeline.llm import LLMClient
        from proofjudge.pipeline.summarization import run_summarization

        db = Database(settings.db_path)
        async with LLMClient(
            api_key=settings.anthropic_api_key,
            model=settings.summarization_model,
            concurrency=settings.summarization_concurrency,
            request_interval=settings.summarization_request_interval,
        ) as llm:
            count = await run_summarization(llm, db, settings, limit=limit)
            console.print(f"Summarized {count} PRs.")
        db.close()

    asyncio.run(_run())
    status()


@app.command()
def assemble(
    limit: int | None = typer.Option(None, help="Max PRs to assemble"),
    dataset_version: str = typer.Option("v0.1", help="Dataset version string"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Phase 6: Assemble HIGH_VALUE pairs into HuggingFace dataset."""
    _setup_logging(verbose)
    settings = _get_settings()

    from proofjudge.pipeline.assembly import run_assembly

    db = Database(settings.db_path)
    count = run_assembly(db, settings, limit=limit, dataset_version=dataset_version)
    console.print(f"Assembled {count} PRs.")
    db.close()

    status()


@app.command()
def status(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Show pipeline progress across all phases."""
    _setup_logging(verbose)
    settings = _get_settings()
    db = Database(settings.db_path)
    counts = db.get_phase_counts()
    db.close()

    table = Table(title="ProofJudge Pipeline Status")
    table.add_column("Phase", style="cyan")
    table.add_column("Count", justify="right", style="green")

    table.add_row("Discovered", str(counts["discovered"]))
    table.add_row("Enriched", str(counts["enriched"]))
    table.add_row("Qualified", str(counts["qualified"]))
    table.add_row("Extracted", str(counts["extracted"]))
    table.add_row("Parsed", str(counts["parsed"]))
    table.add_row("Summarized", str(counts["summarized"]))
    table.add_row("Assembled", str(counts["assembled"]))
    table.add_row("Failed (3+ errors)", str(counts["failed"]))

    console.print(table)


@app.command()
def sample(
    n: int = typer.Option(50, help="Number of PRs to process"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run the full pipeline on a sample of N qualifying PRs."""
    _setup_logging(verbose)
    settings = _get_settings()

    async def _run() -> None:
        from proofjudge.pipeline.discovery import run_discovery
        from proofjudge.pipeline.enrichment import run_enrichment
        from proofjudge.pipeline.extraction import run_extraction
        from proofjudge.pipeline.llm import LLMClient
        from proofjudge.pipeline.parsing import run_parsing
        from proofjudge.pipeline.summarization import run_summarization

        db = Database(settings.db_path)
        async with GitHubClient(settings.github_token) as client:
            # Phase 1+2: Discover enough PRs to get N qualifying ones
            console.print(
                f"[cyan]Phase 1+2:[/cyan] Discovering PRs (scan limit: {n * 20})..."
            )
            await run_discovery(
                client,
                db,
                settings,
                full_scan=True,
                keywords=True,
                scan_limit=n * 20,
            )
            await run_enrichment(client, db, settings)

            # Phase 3: Extract the first N qualifying PRs
            console.print(f"[cyan]Phase 3:[/cyan] Extracting top {n} qualifying PRs...")
            extract_count = await run_extraction(client, db, settings, limit=n)
            console.print(f"[green]Extracted {extract_count} PRs.[/green]")

            # Phase 4: Parse proof pairs
            console.print("[cyan]Phase 4:[/cyan] Parsing proof pairs...")
            parse_count = await run_parsing(client, db, settings, limit=n)
            console.print(f"[green]Parsed {parse_count} PRs.[/green]")

        # Phase 5: Summarize (requires anthropic key)
        if settings.anthropic_api_key:
            console.print("[cyan]Phase 5:[/cyan] Summarizing proof pairs...")
            async with LLMClient(
                api_key=settings.anthropic_api_key,
                model=settings.summarization_model,
                concurrency=settings.summarization_concurrency,
                request_interval=settings.summarization_request_interval,
            ) as llm:
                summ_count = await run_summarization(llm, db, settings, limit=n)
                console.print(f"[green]Summarized {summ_count} PRs.[/green]")

            # Phase 6: Assembly
            from proofjudge.pipeline.assembly import run_assembly

            console.print("[cyan]Phase 6:[/cyan] Assembling dataset...")
            asm_count = run_assembly(db, settings, limit=n)
            console.print(f"[green]Assembled {asm_count} PRs.[/green]")
        else:
            console.print(
                "[yellow]Skipping phases 5+6:[/yellow] ANTHROPIC_API_KEY not set"
            )

        db.close()

    asyncio.run(_run())
    status()


if __name__ == "__main__":
    app()
