# Repository analysis stage: detects languages, frameworks, dependency installs and validation commands, with no LLM.
from __future__ import annotations
import configparser
import json
import re
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from .common import track_run
# Dependencies are installed here inside the clone; dot-prefixed so pytest and the planner's tree skip it.
DEPS_DIR = ".agent_swarm"
PY_DEPS_DIR = f"{DEPS_DIR}/pydeps"
SKIP_DIRS = {".git", "node_modules", "__pycache__", "venv", ".venv", "env", "dist", "build", DEPS_DIR, ".tox", ".mypy_cache", ".pytest_cache"}
MAX_SCAN_FILES = 5000
NPM_DEFAULT_TEST = "no test specified"
PY_REQUIREMENT_FILES = (
    "requirements.txt",
    "requirements-dev.txt",
    "requirements_dev.txt",
    "requirements-test.txt",
    "requirements_test.txt",
    "dev-requirements.txt",
    "test-requirements.txt",
)
PY_FRAMEWORKS = {"django": "Django", "flask": "Flask", "fastapi": "FastAPI", "starlette": "Starlette"}
JS_FRAMEWORKS = {
    "next": "Next.js", "react": "React", "vue": "Vue", "svelte": "Svelte", "@angular/core": "Angular",
    "express": "Express", "fastify": "Fastify", "@nestjs/core": "NestJS", "vite": "Vite",
}
@dataclass
class CheckSpec:
    # One validation command. kind "py_compile" is expanded by the Tester with the changed .py files.
    # category is install | build | test | lint; only "test" checks can make the test status PASS.
    name: str
    command: list[str]
    required: bool = True
    kind: str = "command"
    category: str = "test"
@dataclass
class ProjectProfile:
    # Everything the Planner and Tester need to know about how this repository is built and validated.
    languages: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    package_managers: list[str] = field(default_factory=list)
    install_steps: list[CheckSpec] = field(default_factory=list)
    checks: list[CheckSpec] = field(default_factory=list)
    manifests: list[str] = field(default_factory=list)
    has_tests: bool = False
    file_count: int = 0
    def as_dict(self) -> dict:
        # Plain-dict form for AgentRun output and the runner API.
        return asdict(self)
    def summary(self) -> str:
        # One-paragraph description embedded in the Planner and Reviewer prompts.
        parts = [f"Languages: {', '.join(self.languages) or 'unknown'}"]
        if self.frameworks:
            parts.append(f"Frameworks: {', '.join(self.frameworks)}")
        if self.package_managers:
            parts.append(f"Package managers: {', '.join(self.package_managers)}")
        checks = [f"{c.name} ({' '.join(c.command) if c.command else c.kind})" for c in self.checks]
        parts.append(f"Validation: {', '.join(checks) if checks else 'no test suite or build detected'}")
        return ". ".join(parts) + "."
def detect_project(repo_path: str) -> ProjectProfile:
    # Inspects manifests and file names to build a ProjectProfile; never executes anything from the repo.
    root = Path(repo_path)
    profile = ProjectProfile()
    files = _list_files(root)
    profile.file_count = len(files)
    suffixes = {Path(f).suffix for f in files}
    names = {Path(f).name for f in files}
    if (root / "package.json").is_file():
        _detect_node(root, profile, names)
    if suffixes & {".py"} or any((root / m).is_file() for m in ("pyproject.toml", "setup.py", "setup.cfg", *PY_REQUIREMENT_FILES)):
        _detect_python(root, profile, files)
    if not profile.languages:
        if suffixes & {".ts", ".tsx"}:
            profile.languages.append("TypeScript")
        elif suffixes & {".js", ".jsx", ".mjs"}:
            profile.languages.append("JavaScript")
    return profile
def run_analyzer(ctx) -> ProjectProfile:
    # Pipeline stage wrapper: detects the profile, records it in the trace, and stores it on the context.
    with track_run(ctx, agent_type="analyzer", provider="none", input_context={"github_url": ctx.github_url}) as run:
        profile = detect_project(ctx.local_path)
        run.output = {**profile.as_dict(), "summary": profile.summary(), "base_branch": ctx.base_branch, "base_sha": ctx.base_sha}
        ctx.profile = profile
        return profile
def _list_files(root: Path) -> list[str]:
    # Repo-relative file paths, skipping dependency and build directories, capped for huge repos.
    out: list[str] = []
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if path.is_file():
            out.append(str(rel).replace("\\", "/"))
            if len(out) >= MAX_SCAN_FILES:
                break
    return out
def _detect_node(root: Path, profile: ProjectProfile, names: set[str]) -> None:
    # Reads package.json scripts and lockfiles to choose install, build, test and lint commands.
    try:
        pkg = json.loads((root / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pkg = {}
    scripts = pkg.get("scripts") or {}
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    is_ts = (root / "tsconfig.json").is_file() or "typescript" in deps
    profile.languages.append("TypeScript" if is_ts else "JavaScript")
    profile.frameworks += [label for dep, label in JS_FRAMEWORKS.items() if dep in deps]
    profile.manifests.append("package.json")
    if (root / "pnpm-lock.yaml").is_file():
        manager, install = "pnpm", ["corepack", "pnpm", "install", "--frozen-lockfile"]
        profile.manifests.append("pnpm-lock.yaml")
    elif (root / "yarn.lock").is_file():
        manager, install = "yarn", ["corepack", "yarn", "install", "--frozen-lockfile"]
        profile.manifests.append("yarn.lock")
    elif (root / "package-lock.json").is_file() or (root / "npm-shrinkwrap.json").is_file():
        manager, install = "npm", ["npm", "ci", "--no-audit", "--no-fund"]
        profile.manifests.append("package-lock.json")
    else:
        manager, install = "npm", ["npm", "install", "--no-audit", "--no-fund"]
    profile.package_managers.append(manager)
    if deps:
        profile.install_steps.append(CheckSpec(name=f"{manager} install", command=install, category="install"))
    if "build" in scripts:
        profile.checks.append(CheckSpec(name="build", command=["npm", "run", "build", "--silent"], category="build"))
    elif is_ts and "typescript" in deps and (root / "tsconfig.json").is_file():
        profile.checks.append(CheckSpec(name="typecheck", command=["npx", "--no-install", "tsc", "--noEmit"], category="build"))
    test_script = scripts.get("test") or ""
    if test_script and NPM_DEFAULT_TEST not in test_script:
        profile.checks.append(CheckSpec(name="npm test", command=["npm", "test", "--silent"]))
        profile.has_tests = True
    if "lint" in scripts:
        profile.checks.append(CheckSpec(name="lint", command=["npm", "run", "lint", "--silent"], required=False, category="lint"))
def _detect_python(root: Path, profile: ProjectProfile, files: list[str]) -> None:
    # Reads requirements/pyproject to choose dependency installs, then test, compile and lint checks.
    profile.languages.append("Python")
    pyproject = _read_toml(root / "pyproject.toml")
    setup_cfg = _read_ini(root / "setup.cfg")
    tox_ini = _read_ini(root / "tox.ini")
    requirement_files = [name for name in PY_REQUIREMENT_FILES if (root / name).is_file()]
    profile.manifests += requirement_files + [m for m in ("pyproject.toml", "setup.py", "setup.cfg") if (root / m).is_file()]
    dep_text = " ".join(_safe_read(root / name).lower() for name in requirement_files) + json.dumps(pyproject).lower()
    profile.frameworks += [label for key, label in PY_FRAMEWORKS.items() if re.search(rf"\b{re.escape(key)}\b", dep_text)]
    profile.package_managers.append("pip")
    pip = ["python", "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--quiet", "--target", PY_DEPS_DIR]
    if requirement_files:
        args: list[str] = []
        for name in requirement_files:
            args += ["-r", name]
        profile.install_steps.append(CheckSpec(name="pip install", command=pip + args, category="install"))
    elif (root / "pyproject.toml").is_file() or (root / "setup.py").is_file():
        profile.install_steps.append(CheckSpec(name="pip install", command=pip + ["."], category="install"))
    profile.checks.append(CheckSpec(name="compile", command=[], kind="py_compile", category="build"))
    has_pytest_config = (
        (root / "pytest.ini").is_file()
        or (root / "conftest.py").is_file()
        or "pytest" in ((pyproject.get("tool") or {}))
        or setup_cfg.has_section("tool:pytest")
        or tox_ini.has_section("pytest")
    )
    test_files = [f for f in files if re.search(r"(^|/)(test_[^/]*|[^/]*_test)\.py$", f)]
    if test_files or has_pytest_config:
        profile.checks.append(CheckSpec(name="pytest", command=["python", "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"]))
        profile.has_tests = True
    elif (root / "manage.py").is_file() and any(f.endswith("tests.py") for f in files):
        profile.checks.append(CheckSpec(name="django tests", command=["python", "manage.py", "test", "--noinput"]))
        profile.has_tests = True
    tool = pyproject.get("tool") or {}
    if "ruff" in tool or (root / "ruff.toml").is_file() or (root / ".ruff.toml").is_file():
        profile.checks.append(CheckSpec(name="ruff", command=["ruff", "check", ".", "--extend-exclude", DEPS_DIR], required=False, category="lint"))
    elif (root / ".flake8").is_file() or setup_cfg.has_section("flake8") or tox_ini.has_section("flake8"):
        profile.checks.append(CheckSpec(name="flake8", command=["python", "-m", "flake8", "--extend-exclude", DEPS_DIR], required=False, category="lint"))
def _read_toml(path: Path) -> dict:
    # Parses a TOML file, returning {} if it's missing or malformed.
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return {}
def _read_ini(path: Path) -> configparser.ConfigParser:
    # Parses an INI file, returning an empty parser if it's missing or malformed.
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(path.read_text(encoding="utf-8"))
    except (OSError, configparser.Error, UnicodeDecodeError):
        pass
    return parser
def _safe_read(path: Path) -> str:
    # Reads a text file, returning "" on any error.
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
