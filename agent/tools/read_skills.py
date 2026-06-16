from pathlib import Path

SKILLS_ROOT = Path(__file__).parent.parent.parent / "Skills"

# Map short names to SKILL.md paths
SKILL_MAP = {
    "pdf":           SKILLS_ROOT / "pdf"           / "SKILL.md",
    "excel":         SKILLS_ROOT / "excel"         / "SKILL.md",
    "bankstatement": SKILLS_ROOT / "bankstatement" / "SKILL.md",
}


def read_skills_doc(skill: str = "pdf", skills_path: str = None) -> dict:
    """Read a named skills documentation file.

    skill: one of "pdf", "excel" (default "pdf")
    skills_path: optional explicit path override
    """
    if skills_path:
        path = Path(skills_path)
    else:
        path = SKILL_MAP.get(skill)
        if path is None:
            available = list(SKILL_MAP.keys())
            return {
                "ok": False,
                "error": f"Unknown skill '{skill}'. Available: {available}",
            }

    if not path.exists():
        return {
            "ok": False,
            "error": f"Skills file not found: {path}",
        }

    content = path.read_text(encoding="utf-8")
    return {
        "ok": True,
        "skill": skill,
        "path": str(path),
        "content": content,
        "size_chars": len(content),
    }
