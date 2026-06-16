from __future__ import annotations

from typing import Any

from ..analysis_models import AgentResult, RepositoryContext
from ..deploy_detector import detect_deployment
from ..test_detector import detect_tests
from .base_agent import BaseAgent, score_to_confidence


class TestDeployAgent(BaseAgent):
    name = "测试部署 Agent"
    input_summary = "test_detector.py + deploy_detector.py + CI/Docker/env evidence"

    def analyze(self, context: RepositoryContext, shared: dict[str, Any]) -> AgentResult:
        context_dict = context.to_dict()
        tests = detect_tests(context.local_path, shared.get("tech_stack") or {}, context_dict)
        deploy = detect_deployment(context.local_path, context_dict)
        score = round((tests.get("score", 0) + deploy.get("score", 0)) / 2, 1)
        test_deploy = {"score": score, "tests": tests, "deployment": deploy}
        shared["test_deploy"] = test_deploy
        evidence = [
            {"type": "test_files", "items": tests.get("test_files", [])[:12]},
            {"type": "test_frameworks", "items": tests.get("frameworks", [])},
            {"type": "deploy_files", "items": deploy.get("deploy_files", [])},
            {"type": "startup_scripts", "items": deploy.get("startup_scripts", {})},
        ]
        findings = [
            f"测试文件 {tests.get('test_file_count', 0)} 个，测试框架：{', '.join(tests.get('frameworks') or ['未识别'])}。",
            f"Docker：{'有' if deploy.get('dockerfile') else '无'}，Compose：{'有' if deploy.get('docker_compose') else '无'}，CI：{'有' if deploy.get('github_actions') else '无'}。",
            f"环境变量示例：{', '.join(deploy.get('env_examples') or ['未检测到'])}。",
        ]
        suggestions = (tests.get("suggestions") or []) + (deploy.get("suggestions") or [])
        return self.build_result(
            summary=f"测试与部署成熟度 {score}/10。",
            findings=findings,
            evidence=evidence,
            score=score,
            suggestions=suggestions,
            confidence=score_to_confidence(score),
            raw_output=test_deploy,
            tools_used=["test_detector.py", "deploy_detector.py"],
        )
