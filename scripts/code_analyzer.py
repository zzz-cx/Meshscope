#!/usr/bin/env python3
"""
代码库统计分析工具
统计每个模块的代码行数、文件数量、使用的编程语言等
"""
import os
import json
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Any

# 语言扩展名映射
LANGUAGE_EXTENSIONS = {
    '.py': 'Python',
    '.js': 'JavaScript',
    '.ts': 'TypeScript',
    '.tsx': 'TypeScript',
    '.jsx': 'JavaScript',
    '.json': 'JSON',
    '.yaml': 'YAML',
    '.yml': 'YAML',
    '.md': 'Markdown',
    '.sh': 'Shell',
    '.bat': 'Batch',
    '.ps1': 'PowerShell',
    '.html': 'HTML',
    '.css': 'CSS',
    '.sql': 'SQL',
    '.log': 'Log',
    '.txt': 'Text',
}

# 需要忽略的目录
IGNORE_DIRS = {
    '__pycache__', '.git', '.idea', 'node_modules', 
    '.pytest_cache', '.vscode', 'results', 'models_output'
}

# 需要忽略的文件模式
IGNORE_PATTERNS = {
    '.pyc', '.pyo', '.pyd', '.so', '.dll', '.exe',
    '.log', '.cache', '.lock'
}

def count_lines(file_path: Path) -> int:
    """统计文件行数"""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return len(f.readlines())
    except Exception:
        return 0

def get_language(file_path: Path) -> str:
    """根据文件扩展名判断语言"""
    ext = file_path.suffix.lower()
    return LANGUAGE_EXTENSIONS.get(ext, 'Other')

def should_ignore(path: Path) -> bool:
    """判断是否应该忽略该路径"""
    # 检查目录名
    for part in path.parts:
        if part in IGNORE_DIRS:
            return True
    
    # 检查文件扩展名
    if path.is_file():
        for pattern in IGNORE_PATTERNS:
            if pattern in path.name:
                return True
    
    return False

def analyze_directory(root_dir: Path) -> Dict[str, Any]:
    """分析目录结构"""
    stats = defaultdict(lambda: {
        'files': 0,
        'lines': 0,
        'languages': defaultdict(lambda: {'files': 0, 'lines': 0}),
        'submodules': {}
    })
    
    for root, dirs, files in os.walk(root_dir):
        root_path = Path(root)
        
        # 过滤忽略的目录
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        
        # 确定模块路径（相对于根目录）
        rel_path = root_path.relative_to(root_dir)
        if rel_path == Path('.'):
            module_name = 'root'
        else:
            module_name = str(rel_path).replace(os.sep, '/')
        
        # 跳过忽略的路径
        if should_ignore(root_path):
            continue
        
        # 统计当前目录的文件
        for file in files:
            file_path = root_path / file
            
            if should_ignore(file_path):
                continue
            
            language = get_language(file_path)
            lines = count_lines(file_path)
            
            # 更新统计
            stats[module_name]['files'] += 1
            stats[module_name]['lines'] += lines
            stats[module_name]['languages'][language]['files'] += 1
            stats[module_name]['languages'][language]['lines'] += lines
    
    return dict(stats)

def format_stats(stats: Dict[str, Any]) -> str:
    """格式化统计结果"""
    output = []
    output.append("=" * 80)
    output.append("代码库统计分析报告")
    output.append("=" * 80)
    output.append("")
    
    # 总体统计
    total_files = sum(s['files'] for s in stats.values())
    total_lines = sum(s['lines'] for s in stats.values())
    
    output.append(f"总体统计:")
    output.append(f"  - 模块数量: {len(stats)}")
    output.append(f"  - 文件总数: {total_files}")
    output.append(f"  - 代码总行数: {total_lines:,}")
    output.append("")
    
    # 按语言统计
    language_stats = defaultdict(lambda: {'files': 0, 'lines': 0})
    for module_stats in stats.values():
        for lang, lang_stats in module_stats['languages'].items():
            language_stats[lang]['files'] += lang_stats['files']
            language_stats[lang]['lines'] += lang_stats['lines']
    
    output.append("按语言统计:")
    for lang in sorted(language_stats.keys()):
        lang_stat = language_stats[lang]
        output.append(f"  - {lang:15s}: {lang_stat['files']:4d} 文件, {lang_stat['lines']:8,d} 行")
    output.append("")
    
    # 按模块统计
    output.append("=" * 80)
    output.append("按模块统计:")
    output.append("=" * 80)
    output.append("")
    
    # 按行数排序
    sorted_modules = sorted(stats.items(), key=lambda x: x[1]['lines'], reverse=True)
    
    for module_name, module_stats in sorted_modules:
        if module_stats['files'] == 0:
            continue
        
        output.append(f"模块: {module_name}")
        output.append(f"  - 文件数: {module_stats['files']}")
        output.append(f"  - 代码行数: {module_stats['lines']:,}")
        
        # 语言分布
        if module_stats['languages']:
            output.append(f"  - 语言分布:")
            for lang in sorted(module_stats['languages'].keys()):
                lang_stat = module_stats['languages'][lang]
                pct = (lang_stat['lines'] / module_stats['lines'] * 100) if module_stats['lines'] > 0 else 0
                output.append(f"      {lang:15s}: {lang_stat['files']:3d} 文件, {lang_stat['lines']:6,d} 行 ({pct:5.1f}%)")
        
        output.append("")
    
    return "\n".join(output)

def generate_json_report(stats: Dict[str, Any], output_file: Path):
    """生成JSON格式的报告"""
    report = {
        'summary': {
            'total_modules': len(stats),
            'total_files': sum(s['files'] for s in stats.values()),
            'total_lines': sum(s['lines'] for s in stats.values())
        },
        'by_language': {},
        'by_module': {}
    }
    
    # 按语言统计
    language_stats = defaultdict(lambda: {'files': 0, 'lines': 0})
    for module_stats in stats.values():
        for lang, lang_stats in module_stats['languages'].items():
            language_stats[lang]['files'] += lang_stats['files']
            language_stats[lang]['lines'] += lang_stats['lines']
    
    report['by_language'] = dict(language_stats)
    
    # 按模块统计
    for module_name, module_stats in stats.items():
        report['by_module'][module_name] = {
            'files': module_stats['files'],
            'lines': module_stats['lines'],
            'languages': {
                lang: {
                    'files': lang_stats['files'],
                    'lines': lang_stats['lines']
                }
                for lang, lang_stats in module_stats['languages'].items()
            }
        }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="代码库统计分析")
    parser.add_argument("--root", type=str, default=".", help="根目录路径")
    parser.add_argument("--output", type=str, help="输出文件路径（可选）")
    parser.add_argument("--json", type=str, help="输出JSON报告路径（可选）")
    
    args = parser.parse_args()
    
    root_dir = Path(args.root).resolve()
    if not root_dir.exists():
        print(f"错误: 目录不存在: {root_dir}")
        return
    
    print(f"正在分析代码库: {root_dir}")
    print("这可能需要一些时间...")
    
    stats = analyze_directory(root_dir)
    report = format_stats(stats)
    
    print(report)
    
    # 输出到文件
    if args.output:
        output_file = Path(args.output)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"\n报告已保存到: {output_file}")
    
    # 输出JSON报告
    if args.json:
        json_file = Path(args.json)
        json_file.parent.mkdir(parents=True, exist_ok=True)
        generate_json_report(stats, json_file)
        print(f"JSON报告已保存到: {json_file}")

if __name__ == "__main__":
    main()

