"""
SeaSync 标准版 — 批量添加 AGPL v3 版权头。
用法：python add_copyright.py
"""
import os

HEADER_LINES = [
    'SeaSync V2.2 - 多源目标关联分析系统',
    'Copyright (C) 2026 荣火',
    '',
    'This program is free software: you can redistribute it and/or modify',
    'it under the terms of the GNU Affero General Public License as published',
    'by the Free Software Foundation, either version 3 of the License, or',
    '(at your option) any later version.',
    '',
    'This program is distributed in the hope that it will be useful,',
    'but WITHOUT ANY WARRANTY; without even the implied warranty of',
    'MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the',
    'GNU Affero General Public License for more details.',
    '',
    'You should have received a copy of the GNU Affero General Public License',
    'along with this program.  If not, see <https://www.gnu.org/licenses/>.',
]

SHORT_HEADER_LINES = [
    'SPDX-License-Identifier: AGPL-3.0-or-later',
    'Copyright (C) 2026 荣火',
]

ROOT = os.path.dirname(os.path.abspath(__file__))


def make_full_header() -> str:
    lines = ['"""'] + HEADER_LINES + ['"""']
    return '\n'.join(lines)


def make_short_header() -> str:
    lines = ['# ' + l for l in SHORT_HEADER_LINES]
    return '\n'.join(lines)


def has_header(text: str) -> bool:
    return "Copyright (C) 2026 荣火" in text[:500]


def add_header(filepath: str) -> bool:
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    if has_header(content):
        return False

    stripped = content.lstrip()
    if stripped.startswith('"""'):
        end_doc = content.index('"""', content.index('"""') + 3) + 3
        insert_pos = content.index('\n', end_doc) + 1
        new_content = content[:insert_pos] + '\n' + make_short_header() + '\n' + content[insert_pos:]
    else:
        new_content = make_full_header() + '\n\n' + content

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_content)
    return True


def main():
    count = 0
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith('.')
                       and d not in ('__pycache__', 'dist', 'build')]
        for fn in filenames:
            if fn.endswith('.py'):
                fp = os.path.join(dirpath, fn)
                if add_header(fp):
                    print(f'  + {os.path.relpath(fp, ROOT)}')
                    count += 1
    print(f'\n已添加版权头: {count} 个文件')
    print('跳过（已有版权头）: 其余文件')


if __name__ == '__main__':
    main()
