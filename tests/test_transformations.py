"""Unit tests for transformation logic. Expanded in Phase 2."""

from pgx_latam.utils.star_allele_scope import (
    OutOfScopeGeneError,
    assert_in_scope,
    in_scope_symbols,
)


class TestStarAlleleScope:
    def test_cyp2c19_is_in_scope(self) -> None:
        scope = assert_in_scope("CYP2C19")
        assert scope.in_scope is True
        assert "clopidogrel" in scope.key_drugs

    def test_cypd26_raises_out_of_scope(self) -> None:
        import pytest

        with pytest.raises(OutOfScopeGeneError, match="CYP2D6"):
            assert_in_scope("CYP2D6")

    def test_unknown_gene_raises_out_of_scope(self) -> None:
        import pytest

        with pytest.raises(OutOfScopeGeneError):
            assert_in_scope("FAKE1")

    def test_in_scope_symbols_returns_list(self) -> None:
        symbols = in_scope_symbols()
        assert "CYP2C19" in symbols
        assert "CYP2D6" not in symbols
        assert symbols == sorted(symbols)

    def test_all_in_scope_genes_have_cpic_level_a(self) -> None:
        from pgx_latam.utils.star_allele_scope import IN_SCOPE_GENES

        for gene in in_scope_symbols():
            assert IN_SCOPE_GENES[gene].cpic_level == "A", (
                f"{gene} is in scope but does not have CPIC level A"
            )
