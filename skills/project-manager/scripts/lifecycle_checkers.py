#!/usr/bin/env python3
import argparse
import json
import re
from datetime import date
from pathlib import Path

import yaml


PLACEHOLDERS = {"", "-", "待补充", "todo", "tbd", "n/a"}


def finding(severity: str, code: str, title: str, detail: str, advice: str) -> dict:
    return {"severity": severity, "code": code, "title": title, "detail": detail, "advice": advice}


def report(findings: list[dict], passes: list[str]) -> dict:
    high = sum(item["severity"] == "high" for item in findings)
    medium = sum(item["severity"] == "medium" for item in findings)
    decision = "block" if high else "revise" if medium else "allow"
    return {
        "decision": {"allow": "ALLOW_TO_REVIEW", "revise": "REVISE_BEFORE_REVIEW", "block": "BLOCK"}[decision],
        "normalized_decision": decision,
        "risk": "high" if high else "medium" if medium else "low",
        "passes": passes,
        "findings": findings,
    }


def is_placeholder(value: object) -> bool:
    return str(value or "").strip().lower() in PLACEHOLDERS


HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}


def collect_refs(value: object) -> list[str]:
    if isinstance(value, dict):
        return ([value["$ref"]] if isinstance(value.get("$ref"), str) else []) + [ref for child in value.values() for ref in collect_refs(child)]
    if isinstance(value, list):
        return [ref for child in value for ref in collect_refs(child)]
    return []


def resolve_pointer(document: object, pointer: str) -> bool:
    current = document
    for part in pointer.removeprefix("#/").split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or key not in current:
            return False
        current = current[key]
    return True


def validate_refs(path: Path, document: dict) -> list[str]:
    broken = []
    cache: dict[Path, object] = {path.resolve(): document}
    for ref in collect_refs(document):
        file_part, _, fragment = ref.partition("#")
        target_path = (path.parent / file_part).resolve() if file_part else path.resolve()
        try:
            target = cache.setdefault(target_path, yaml.safe_load(target_path.read_text(encoding="utf-8")))
        except (OSError, yaml.YAMLError):
            broken.append(ref)
            continue
        if fragment and not resolve_pointer(target, f"#/{fragment.lstrip('/')}"):
            broken.append(ref)
    return broken


def operations(document: dict) -> set[tuple[str, str]]:
    return {(route, method.lower()) for route, item in document.get("paths", {}).items() if isinstance(item, dict) for method in item if method.lower() in HTTP_METHODS}


def analyze_openapi(path: Path, baseline: Path | None = None) -> dict:
    findings, passes = [], []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return report([finding("high", "openapi.invalid", "OpenAPI 无法解析", str(exc), "修复文件路径或 YAML 语法。")], [])
    if not isinstance(data, dict) or not str(data.get("openapi", "")).startswith("3."):
        findings.append(finding("high", "openapi.version", "OpenAPI 版本无效", "缺少 OpenAPI 3.x 版本声明。", "设置 `openapi: 3.0.x` 或 `3.1.x`。"))
    else:
        passes.append("OpenAPI 版本有效")
    info = data.get("info", {}) if isinstance(data, dict) else {}
    if not isinstance(info, dict) or any(is_placeholder(info.get(key)) for key in ("title", "version")):
        findings.append(finding("medium", "openapi.info", "接口元信息不完整", "info.title 或 info.version 缺失。", "补齐接口名称和版本。"))
    else:
        passes.append("接口元信息完整")
    paths = data.get("paths", {}) if isinstance(data, dict) else {}
    if not isinstance(paths, dict) or not paths:
        findings.append(finding("high", "openapi.paths", "缺少接口路径", "paths 为空。", "至少定义本功能涉及的接口 path、method 和 response。"))
    else:
        weak = []
        for route, item in paths.items():
            route_operations = [op for method, op in (item or {}).items() if method.lower() in HTTP_METHODS]
            if not route_operations or any(not isinstance(op, dict) or not op.get("responses") for op in route_operations):
                weak.append(str(route))
        if weak:
            findings.append(finding("high", "openapi.operations", "接口操作不完整", f"缺少 method 或 responses：{', '.join(weak)}。", "补齐每个路径的 HTTP 方法和响应定义。"))
        else:
            passes.append(f"接口路径有效：{len(paths)} 个")
    if isinstance(data, dict):
        broken_refs = validate_refs(path, data)
        if broken_refs:
            findings.append(finding("high", "openapi.refs", "OpenAPI 引用失效", f"无法解析：{', '.join(broken_refs)}。", "修复内部 JSON Pointer 或本地引用文件路径。"))
        else:
            passes.append("OpenAPI 引用有效")
    if baseline:
        try:
            old = yaml.safe_load(baseline.read_text(encoding="utf-8"))
            removed = operations(old) - operations(data)
        except (OSError, yaml.YAMLError, AttributeError) as exc:
            findings.append(finding("high", "openapi.baseline", "OpenAPI 基线不可用", str(exc), "提供可解析的历史 OpenAPI 文件。"))
        else:
            if removed:
                labels = [f"{method.upper()} {route}" for route, method in sorted(removed)]
                findings.append(finding("high", "openapi.breaking.removed", "检测到破坏性接口删除", f"已删除：{', '.join(labels)}。", "恢复接口，或记录版本化迁移和消费者批准。"))
            else:
                passes.append("未删除基线中的接口操作")
    return report(findings, passes)


def section(markdown: str, heading: str) -> str:
    match = re.search(rf"^##\s+{re.escape(heading)}\s*$([\s\S]*?)(?=^##\s+|\Z)", markdown, re.MULTILINE)
    return match.group(1).strip() if match else ""


def analyze_test_report(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return report([finding("high", "test-report.missing", "测试报告不可读", str(exc), "补齐测试报告文件。")], [])
    findings, passes = [], []
    required = ["基本信息", "执行摘要", "缺陷与阻塞", "回归与 smoke", "测试结论"]
    missing = [name for name in required if not section(text, name)]
    if missing:
        findings.append(finding("high", "test-report.sections", "测试报告章节缺失", f"缺少：{', '.join(missing)}。", "按标准测试报告模板补齐章节。"))
    else:
        passes.append("测试报告章节完整")
    conclusion = section(text, "测试结论")
    if not conclusion or "待补充" in conclusion:
        findings.append(finding("high", "test-report.conclusion", "测试结论未确认", "测试结论为空或仍为占位值。", "明确通过、有条件通过或不通过，并记录 owner。"))
    else:
        passes.append("测试结论已确认")
    return report(findings, passes)


def analyze_retrospective(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return report([finding("high", "retro.missing", "复盘文档不可读", str(exc), "补齐复盘文档。")], [])
    findings, passes = [], []
    required = ["2. 目标与结果回顾", "3. 时间线", "5. 问题与根因", "7. 改进动作", "8. 后续结论"]
    missing = [name for name in required if not section(text, name)]
    if missing:
        findings.append(finding("high", "retro.sections", "复盘章节缺失", f"缺少：{', '.join(missing)}。", "按复盘模板补齐目标、根因、动作和结论。"))
    else:
        passes.append("复盘章节完整")
    actions = section(text, "7. 改进动作")
    if "待补充" in actions or not re.search(r"\d{4}-\d{2}-\d{2}", actions):
        findings.append(finding("medium", "retro.actions", "改进动作不可执行", "动作仍有占位值或没有明确截止日期。", "为每个动作指定 Owner、日期和状态。"))
    else:
        passes.append("改进动作可跟踪")
    return report(findings, passes)


def analyze_project_status(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return report([finding("high", "status.invalid", "项目台账不可解析", str(exc), "创建或修复项目状态 YAML。")], [])
    findings, passes = [], []
    if not isinstance(data, dict) or is_placeholder(data.get("project")) or is_placeholder(data.get("owner")):
        findings.append(finding("high", "status.basic", "项目基本信息缺失", "project 或 owner 未填写。", "补齐项目名称和单一负责人。"))
    milestones = data.get("milestones", []) if isinstance(data, dict) else []
    if not milestones:
        findings.append(finding("medium", "status.milestones", "没有里程碑", "milestones 为空。", "登记里程碑、Owner、截止日期和状态。"))
    else:
        milestone_errors = 0
        for index, item in enumerate(milestones, 1):
            if not isinstance(item, dict) or any(is_placeholder(item.get(key)) for key in ("name", "owner", "due", "status")):
                findings.append(finding("high", f"status.milestone.{index}", "里程碑记录不完整", f"第 {index} 个里程碑缺少 name、owner、due 或 status。", "补齐里程碑必填字段。"))
                milestone_errors += 1
                continue
            try:
                overdue = date.fromisoformat(str(item["due"])) < date.today() and item["status"] not in {"done", "closed"}
            except ValueError:
                overdue = True
            if overdue:
                findings.append(finding("high", f"status.milestone-overdue.{index}", "里程碑已逾期", f"里程碑 `{item['name']}` 截止日期无效或已过期。", "更新计划、Owner 或完成状态。"))
                milestone_errors += 1
        if not milestone_errors:
            passes.append(f"里程碑台账有效：{len(milestones)} 个")
    risks = data.get("risks", []) if isinstance(data, dict) else []
    for index, item in enumerate(risks, 1):
        if not isinstance(item, dict) or any(is_placeholder(item.get(key)) for key in ("risk", "impact", "owner", "action", "due", "status")):
            findings.append(finding("high", f"status.risk.{index}", "风险记录不完整", f"第 {index} 条风险缺少必填字段。", "补齐风险、影响、Owner、动作、截止日期和状态。"))
            continue
        try:
            overdue = date.fromisoformat(str(item["due"])) < date.today() and item["status"] not in {"mitigated", "accepted", "closed"}
        except ValueError:
            overdue = True
        if overdue:
            findings.append(finding("high", f"status.risk-overdue.{index}", "风险动作已逾期", f"风险 `{item['risk']}` 截止日期无效或已过期。", "更新动作、截止日期或关闭状态。"))
    if risks and not any(item["code"].startswith("status.risk") for item in findings):
        passes.append(f"风险台账有效：{len(risks)} 条")
    return report(findings, passes)


ANALYZERS = {"api-contract": analyze_openapi, "test-report": analyze_test_report, "retrospective": analyze_retrospective, "project-status": analyze_project_status}


def run_cli(module: str) -> int:
    parser = argparse.ArgumentParser(description=f"Run {module} governance checks.")
    parser.add_argument("--input", required=True, help="Input artifact path")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output", help="Optional output report path")
    parser.add_argument("--baseline", help="Previous OpenAPI file used to detect removed operations" if module == "api-contract" else argparse.SUPPRESS)
    parser.add_argument("--fail-on", choices=["revise", "block"], help="Return exit code 1 when the decision reaches this threshold")
    args = parser.parse_args()
    result = analyze_openapi(Path(args.input), Path(args.baseline) if args.baseline else None) if module == "api-contract" else ANALYZERS[module](Path(args.input))
    if args.format == "json":
        rendered = json.dumps({"module": f"{module}-checker", "input": args.input, **result}, ensure_ascii=False, indent=2)
    else:
        lines = [f"# {module} Report", "", f"- Decision: `{result['decision']}`", f"- Decision Code: `{result['normalized_decision']}`", f"- Risk: `{result['risk']}`", "", "## Findings", ""]
        lines.extend([f"- `{item['severity']}` {item['title']}：{item['detail']} {item['advice']}" for item in result["findings"]] or ["No blocking findings."])
        rendered = "\n".join(lines) + "\n"
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered)
    order = {"allow": 0, "revise": 1, "block": 2}
    return 1 if args.fail_on and order[result["normalized_decision"]] >= order[args.fail_on] else 0
