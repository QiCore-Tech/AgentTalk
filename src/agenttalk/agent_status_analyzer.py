from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class AgentActivityState(str, Enum):
    """Agent 活动状态的语义分类"""
    IDLE = "idle"           # 等待输入，显示 prompt
    WORKING = "working"     # 正在执行任务，有正常输出
    THINKING = "thinking"   # 正在思考/生成，输出缓慢或显示进度
    ERROR = "error"         # 出现错误信息
    CRASHED = "crashed"     # 进程崩溃或 pane 消失
    STUCK = "stuck"         # 卡住无响应（长时间无输出）
    COMPLETED = "completed" # 任务已完成，等待新指令


@dataclass
class AgentStateAnalysis:
    """LLM 分析结果"""
    state: AgentActivityState
    confidence: float       # 0-1 置信度
    description: str        # 状态描述
    suggested_action: Optional[str] = None  # 建议操作
    raw_output_snippet: str = ""  # 分析的原始输出片段


# 系统提示词 - 让 LLM 分析 terminal 输出
STATUS_ANALYSIS_PROMPT = """You are an expert at analyzing terminal output from AI agent CLIs (like Claude Code, Codex, etc.). 

Analyze the following terminal output and determine the agent's current state. Focus on:
1. Is the agent actively working, idle, or stuck?
2. Are there any error messages or stack traces?
3. Is the agent waiting for user input?
4. Has the agent completed its current task?

Output must be a JSON object with this exact structure:
{
    "state": "idle|working|thinking|error|crashed|stuck|completed",
    "confidence": 0.0-1.0,
    "description": "Brief description of what the agent is doing",
    "suggested_action": "Optional suggestion for what to do next"
}

State definitions:
- idle: Agent is waiting for input, showing a prompt (like ">", "$", "➜")
- working: Agent is actively executing commands, showing normal output
- thinking: Agent is processing/generating, may show progress indicators or be slow
- error: Agent encountered an error, crash, or exception
- crashed: The process has crashed or the pane is dead
- stuck: Agent appears frozen, no output for a long time
- completed: Agent finished its task and is ready for next instruction

Rules:
- Be conservative with "error" - only if there's a real error, not just discussing errors
- "stuck" only if there's genuinely no activity (not just slow processing)
- Look for shell prompts, completion markers, or "Done" messages
- Ignore ANSI escape sequences and terminal artifacts
"""


class AgentStatusAnalyzer:
    """使用 LLM 分析 agent 终端状态"""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini", base_url: Optional[str] = None):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model
        self.base_url = base_url or os.environ.get("OPENAI_BASE_URL")
        self._cache: dict[str, tuple[str, AgentStateAnalysis]] = {}  # fingerprint -> (output, analysis)
        self._last_analysis_time: dict[str, float] = {}
        self.min_interval = 30  # 最小分析间隔（秒）
        
    def should_analyze(self, short_id: str, fingerprint: str) -> bool:
        """检查是否需要重新分析"""
        # 检查缓存
        if short_id in self._cache:
            cached_fingerprint, _ = self._cache[short_id]
            if cached_fingerprint == fingerprint:
                return False  # 输出未变化
        
        # 检查时间间隔
        last_time = self._last_analysis_time.get(short_id, 0)
        if time.time() - last_time < self.min_interval:
            return False  # 距离上次分析太近
            
        return True
    
    def analyze(self, short_id: str, terminal_output: str) -> AgentStateAnalysis:
        """分析 terminal 输出，返回 agent 状态"""
        from agenttalk.tmux import output_fingerprint
        
        fingerprint = output_fingerprint(terminal_output)
        
        # 检查缓存
        if not self.should_analyze(short_id, fingerprint):
            if short_id in self._cache:
                return self._cache[short_id][1]
        
        # 清理输出（移除 ANSI 序列）
        clean_output = self._clean_terminal_output(terminal_output)
        
        # 只取最后 30 行（减少 token 消耗）
        lines = clean_output.split('\n')[-30:]
        snippet = '\n'.join(lines)
        
        # 调用 LLM 分析
        try:
            analysis = self._call_llm(snippet)
            analysis.raw_output_snippet = snippet[:500]  # 保存原始片段用于调试
        except Exception as e:
            # LLM 调用失败，回退到简单规则
            analysis = self._fallback_analysis(clean_output)
            analysis.description = f"LLM analysis failed ({e}), using fallback"
        
        # 更新缓存
        self._cache[short_id] = (fingerprint, analysis)
        self._last_analysis_time[short_id] = time.time()
        
        return analysis
    
    def _call_llm(self, terminal_output: str) -> AgentStateAnalysis:
        """调用 LLM API 分析状态"""
        import openai
        
        if not self.api_key:
            raise ValueError("OpenAI API key not configured")
        
        client_kwargs = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        
        client = openai.OpenAI(**client_kwargs)
        
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": STATUS_ANALYSIS_PROMPT},
                {"role": "user", "content": f"Terminal output (last 30 lines):\n```\n{terminal_output}\n```"}
            ],
            max_tokens=300,
            temperature=0.1,  # 低温度，更确定性
        )
        
        content = response.choices[0].message.content
        if not content:
            raise ValueError("Empty LLM response")
        
        # Try to parse JSON, fallback to raw text if needed
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            # If not valid JSON, try to extract from markdown code block
            import re
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(1))
            else:
                # Fallback: treat entire response as description
                return AgentStateAnalysis(
                    state=AgentActivityState.WORKING,
                    confidence=0.5,
                    description=content[:200],
                )
        
        return AgentStateAnalysis(
            state=AgentActivityState(result.get("state", "idle")),
            confidence=float(result.get("confidence", 0.5)),
            description=result.get("description", "Unknown state"),
            suggested_action=result.get("suggested_action"),
        )
    
    def _fallback_analysis(self, output: str) -> AgentStateAnalysis:
        """当 LLM 不可用时使用简单规则回退"""
        output_lower = output.lower()
        
        # 检查错误
        if any(term in output_lower for term in ["error:", "traceback", "failed", "panic:"]):
            return AgentStateAnalysis(
                state=AgentActivityState.ERROR,
                confidence=0.7,
                description="Error detected in terminal output (fallback)"
            )
        
        # 检查是否空闲（有 prompt）
        if any(prompt in output for prompt in ["> ", "$ ", "➜ ", "# ", "% "]):
            return AgentStateAnalysis(
                state=AgentActivityState.IDLE,
                confidence=0.6,
                description="Shell prompt detected (fallback)"
            )
        
        # 默认 working
        return AgentStateAnalysis(
            state=AgentActivityState.WORKING,
            confidence=0.5,
            description="Output detected, state unclear (fallback)"
        )
    
    def _clean_terminal_output(self, output: str) -> str:
        """清理 terminal 输出（移除 ANSI 序列等）"""
        import re
        # 移除 ANSI 转义序列
        output = re.sub(r'\x1b\[[0-9;]*[mKHJ]', '', output)
        # 移除 tmux 状态栏
        output = re.sub(r'\[pty-[^:]+:[^\]]+\s+""\s+\d+:\d+\s+[^\]]+\]', '', output)
        # 移除其他 artifacts
        output = re.sub(r'\x1b\?\d+[lh]', '', output)
        output = re.sub(r'\(B', '', output)
        return output.strip()


# 全局分析器实例（lazy init）
_analyzer: Optional[AgentStatusAnalyzer] = None

def get_analyzer() -> AgentStatusAnalyzer:
    """获取全局分析器实例"""
    global _analyzer
    if _analyzer is None:
        _analyzer = AgentStatusAnalyzer()
    return _analyzer
