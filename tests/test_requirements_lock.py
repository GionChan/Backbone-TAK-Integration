"""relay/requirements.lock (hashed, used by the Docker image) agrees with relay/requirements.txt."""
import re
import unittest
from pathlib import Path

RELAY = Path(__file__).resolve().parent.parent / "relay"
PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)", re.M)


def pins(text: str) -> dict:
    return {m.group(1).lower(): m.group(2) for m in PIN.finditer(text)}


class LockTests(unittest.TestCase):
    def test_every_requirement_is_locked_at_the_same_version(self):
        req = pins((RELAY / "requirements.txt").read_text(encoding="utf-8"))
        lock = pins((RELAY / "requirements.lock").read_text(encoding="utf-8"))
        self.assertTrue(req)
        for name, version in req.items():
            self.assertEqual(lock.get(name), version, f"{name}: regenerate relay/requirements.lock")

    def test_every_locked_package_has_hashes(self):
        text = (RELAY / "requirements.lock").read_text(encoding="utf-8")
        blocks = re.split(r"\n(?=[A-Za-z0-9_.-]+==)", text)
        locked = [b for b in blocks if PIN.match(b)]
        self.assertGreaterEqual(len(locked), 4)
        for block in locked:
            self.assertIn("--hash=sha256:", block, block.split()[0])


if __name__ == "__main__":
    unittest.main()
