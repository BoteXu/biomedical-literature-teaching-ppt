"""Offline release checks. No execution of skill content or network access."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SKILL_FILES = (
    'SKILL.md', 'agents/openai.yaml',
    'references/artifact-records.md', 'references/figure-and-export-qa.md',
    'references/narrative-and-narration.md', 'scripts/ppt_workflow.py',
    'README.md', 'LICENSE', 'VERSION', 'examples/narration.json',
)

def validate(root=ROOT):
    errors = []
    for name in SKILL_FILES:
        p = root / name
        if not p.is_file() or p.is_symlink():
            errors.append(f'Missing regular file: {name}')
            continue
        content = p.read_text(encoding='utf-8')
        if re.search(r'(?i)[A-Z]:[\\/](?:Users|GPT|Research_Workspace)|/home/[^/\s]+/|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{24,}', content):
            errors.append(f'Possible private path or credential: {name}')
        if p.suffix == '.md':
            for target in re.findall(r'\]\(([^)]+)\)', content):
                if '://' in target or target.startswith('#') or target.startswith('mailto:'):
                    continue
                local = (p.parent / target.split('#')[0]).resolve()
                if not local.is_relative_to(root.resolve()) or not local.exists():
                    errors.append(f'Broken or escaping local link: {name}: {target}')
    skill = (root / 'SKILL.md').read_text(encoding='utf-8')
    if not skill.startswith('---\n') or '\n---\n' not in skill[4:]:
        errors.append('SKILL.md frontmatter missing')
    if 'name: biomedical-literature-teaching-ppt\n' not in skill or 'description:' not in skill:
        errors.append('Skill identity missing')
    if '$biomedical-literature-teaching-ppt' not in (root/'agents/openai.yaml').read_text(encoding='utf-8'):
        errors.append('UI prompt does not invoke the skill')
    if not re.fullmatch(r'\d+\.\d+\.\d+', (root/'VERSION').read_text().strip()):
        errors.append('VERSION must use major.minor.patch')
    return errors

if __name__ == '__main__':
    found = validate()
    for error in found:
        print(error)
    print(f'Package checks: {len(found)} finding(s), {len(SKILL_FILES)} release files')
    raise SystemExit(bool(found))
