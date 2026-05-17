"""Gene scope definitions: which pharmacogenes are in scope and why.

CYP2D6 is explicitly excluded. See the docstring below for rationale.
Any code path that receives CYP2D6 as input should raise OutOfScopeGeneError.
"""

from dataclasses import dataclass


class OutOfScopeGeneError(ValueError):
    """Raised when a gene is intentionally excluded from this pipeline."""


@dataclass(frozen=True)
class GeneScope:
    symbol: str
    in_scope: bool
    rationale: str
    cpic_level: str
    key_drugs: tuple[str, ...]


IN_SCOPE_GENES: dict[str, GeneScope] = {
    gene.symbol: gene
    for gene in [
        GeneScope(
            symbol="CYP2C19",
            in_scope=True,
            rationale="CPIC A-level; star alleles called from SNPs only (no CNV requirement)",
            cpic_level="A",
            key_drugs=("clopidogrel", "omeprazole", "escitalopram", "sertraline"),
        ),
        GeneScope(
            symbol="CYP2C9",
            in_scope=True,
            rationale="CPIC A-level; SNP-based calling; warfarin dosing algorithm",
            cpic_level="A",
            key_drugs=("warfarin", "phenytoin", "celecoxib", "ibuprofen"),
        ),
        GeneScope(
            symbol="SLCO1B1",
            in_scope=True,
            rationale="CPIC A-level; rs4149056 single-variant actionability for statin myopathy",
            cpic_level="A",
            key_drugs=("simvastatin", "atorvastatin", "rosuvastatin"),
        ),
        GeneScope(
            symbol="VKORC1",
            in_scope=True,
            rationale="CPIC A-level; warfarin dosing algorithm component",
            cpic_level="A",
            key_drugs=("warfarin",),
        ),
        GeneScope(
            symbol="TPMT",
            in_scope=True,
            rationale="CPIC A-level; thiopurine toxicity; high clinical impact in oncology",
            cpic_level="A",
            key_drugs=("azathioprine", "mercaptopurine", "thioguanine"),
        ),
        GeneScope(
            symbol="NUDT15",
            in_scope=True,
            rationale=(
                "CPIC A-level; thiopurine toxicity; particularly relevant in "
                "East/South Asian and Hispanic ancestry"
            ),
            cpic_level="A",
            key_drugs=("azathioprine", "mercaptopurine", "thioguanine"),
        ),
        GeneScope(
            symbol="DPYD",
            in_scope=True,
            rationale="CPIC A-level; fluoropyrimidine toxicity; relevant in GI and breast oncology",
            cpic_level="A",
            key_drugs=("fluorouracil", "capecitabine"),
        ),
        GeneScope(
            symbol="G6PD",
            in_scope=True,
            rationale=(
                "CPIC A-level; hemolytic anemia risk; high deficiency prevalence in LATAM "
                "populations (Afro-Caribbean ancestry)"
            ),
            cpic_level="A",
            key_drugs=("rasburicase", "primaquine", "dapsone"),
        ),
        GeneScope(
            symbol="IFNL3",
            in_scope=True,
            rationale="CPIC A-level; peginterferon response; HCV treatment relevance in LATAM",
            cpic_level="A",
            key_drugs=("peginterferon-alfa-2a", "peginterferon-alfa-2b", "ribavirin"),
        ),
        GeneScope(
            symbol="CYP3A5",
            in_scope=True,
            rationale="CPIC A-level; tacrolimus dosing; relevant for solid organ transplant",
            cpic_level="A",
            key_drugs=("tacrolimus",),
        ),
        GeneScope(
            symbol="CYP2D6",
            in_scope=False,
            rationale=(
                "EXCLUDED: copy number variation (CNV) and complex star-allele structure "
                "require a dedicated caller (Aldy or PyPGx) applied to WGS BAMs. "
                "Standard VCF genotypes are insufficient for reliable diplotype calling. "
                "Will be addressed in a future phase with an appropriate caller integrated "
                "into the Glue job."
            ),
            cpic_level="A",
            key_drugs=(
                "codeine",
                "tramadol",
                "amitriptyline",
                "nortriptyline",
                "paroxetine",
                "fluoxetine",
            ),
        ),
    ]
}


def assert_in_scope(gene_symbol: str) -> GeneScope:
    """Return the GeneScope for a gene or raise OutOfScopeGeneError.

    Args:
        gene_symbol: HGNC gene symbol (e.g., "CYP2C19").

    Returns:
        GeneScope for the gene if it is in scope.

    Raises:
        OutOfScopeGeneError: If the gene is explicitly excluded or unknown.
    """
    scope = IN_SCOPE_GENES.get(gene_symbol)
    if scope is None:
        raise OutOfScopeGeneError(
            f"Gene '{gene_symbol}' is not in the pgx-latam-atlas scope definition. "
            f"In-scope genes: {sorted(g for g, s in IN_SCOPE_GENES.items() if s.in_scope)}"
        )
    if not scope.in_scope:
        raise OutOfScopeGeneError(
            f"Gene '{gene_symbol}' is explicitly excluded from this pipeline. "
            f"Reason: {scope.rationale}"
        )
    return scope


def in_scope_symbols() -> list[str]:
    """Return sorted list of in-scope gene symbols."""
    return sorted(symbol for symbol, scope in IN_SCOPE_GENES.items() if scope.in_scope)
