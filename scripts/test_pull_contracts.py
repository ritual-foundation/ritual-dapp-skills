"""Regression tests for the contract pull utility's input validation."""

from __future__ import annotations

import unittest

from scripts.pull_contracts import validate_contract_address, validate_contract_name


class ContractInputValidationTests(unittest.TestCase):
    def test_accepts_safe_contract_names(self) -> None:
        self.assertEqual(validate_contract_name("TweetRegistry"), "TweetRegistry")
        self.assertEqual(validate_contract_name("agent-v1.2"), "agent-v1.2")

    def test_rejects_path_traversal_and_absolute_names(self) -> None:
        for name in ("../escape", "nested/name", "/tmp/escape", "", ".", ".."):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    validate_contract_name(name)

    def test_accepts_evm_addresses(self) -> None:
        address = "0x0000000000000000000000000000000000000001"
        self.assertEqual(validate_contract_address(address), address)

    def test_rejects_non_evm_addresses(self) -> None:
        for address in ("TBD", "0x1234", "https://example.com", "0xzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz"):
            with self.subTest(address=address):
                with self.assertRaises(ValueError):
                    validate_contract_address(address)

    def test_allows_tbd_only_for_registry_entries(self) -> None:
        self.assertEqual(validate_contract_address("TBD", allow_tbd=True), "TBD")


if __name__ == "__main__":
    unittest.main()
