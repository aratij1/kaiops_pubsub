from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate environment overrides for a selected cloud profile.")
    parser.add_argument("--profile", required=True, choices=["onprem", "azure", "aws", "gcp"])
    parser.add_argument(
        "--profiles-file",
        default=str(Path("scripts/profiles/service-profiles.json")),
        help="Path to the service profile mapping JSON",
    )
    parser.add_argument(
        "--output",
        default=str(Path(".env.profile.generated")),
        help="Output env file with selected profile values",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    profiles_path = Path(args.profiles_file)
    if not profiles_path.exists():
        raise SystemExit(f"Profiles file not found: {profiles_path}")

    profiles = json.loads(profiles_path.read_text(encoding="utf-8"))
    if not isinstance(profiles, dict) or args.profile not in profiles:
        raise SystemExit(f"Profile '{args.profile}' not found in {profiles_path}")

    selected = profiles[args.profile]
    if not isinstance(selected, dict):
        raise SystemExit(f"Profile '{args.profile}' must be an object")

    lines = [f"# Generated profile: {args.profile}"]
    for key, value in selected.items():
        lines.append(f"{key}={value}")

    output_path = Path(args.output)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {output_path} for profile '{args.profile}'")
    print("Load it with your launcher or merge into runtime env before deployment.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
