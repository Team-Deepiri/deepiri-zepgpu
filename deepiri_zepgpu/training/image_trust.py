"""MVP image trust policy for training containers."""

from __future__ import annotations

from pathlib import Path


class ImageTrustError(PermissionError):
    pass


class ImageTrustPolicy:
    """Allowlist of image references (tag and/or digest)."""

    def __init__(self, allowed: set[str] | None = None) -> None:
        self.allowed = {item.strip() for item in (allowed or set()) if item.strip()}

    @classmethod
    def from_file(cls, path: Path) -> ImageTrustPolicy:
        if not path.exists():
            raise FileNotFoundError(f"image allowlist not found: {path}")
        allowed: set[str] = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            allowed.add(stripped)
        if not allowed:
            raise ImageTrustError(f"image allowlist is empty: {path}")
        return cls(allowed)

    def is_trusted(self, image: str) -> bool:
        # Exact tag or digest matches only; no prefix wildcards in MVP.
        return image.strip() in self.allowed

    def assert_trusted(self, image: str) -> None:
        if not self.is_trusted(image):
            raise ImageTrustError(f"training image is not in the trust allowlist: {image}")


DEFAULT_ALLOWLIST_PATH = (
    Path(__file__).resolve().parents[2] / "docker" / "training-images.allowlist"
)
