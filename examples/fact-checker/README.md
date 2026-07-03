# FactChecker

On-chain fact checker for Ritual Chain. Chains HTTP precompile (0x0801) and LLM precompile (0x0802) to verify factual claims against real-world data.

Flow: submitClaim() -> fetchData() -> checkFact() -> getVerdict()

See FactChecker.sol for full implementation and inline docs.
