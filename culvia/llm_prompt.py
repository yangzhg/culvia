from __future__ import annotations

from typing import Sequence


LLM_REVIEW_SYSTEM_PROMPT = (
    "你是一位克制、专业的摄影选片与修图顾问。"
    "请只基于图片本身判断，不臆测拍摄者身份、地点或隐私信息。"
    "输出必须是中文 JSON 对象，不要使用 Markdown。"
)
LLM_REVIEW_TEXT_SYSTEM_PROMPT = (
    "你是一位克制、专业的摄影选片与修图顾问。"
    "你会收到本地模型评分和技术指标，而不是照片本身。"
    "请只基于这些指标做二次评审，不要声称自己直接看到了照片，不臆测拍摄者身份、地点或隐私信息。"
    "输出必须是中文 JSON 对象，不要使用 Markdown。"
)
LLM_REVIEW_USER_PROMPT = """
请评价这张照片，重点服务于“选片”和“后期修图决策”。

评审原则：
- 整体评分以艺术性、情绪感染力、主体表达、构图关系、光影氛围、色彩气质和内容张力为主。
- 技术项作为辅助判断和扣分项；除非清晰度、曝光、噪点、伪影等问题严重破坏主体和情绪，否则不要让技术分主导总评。
- 建议总分约 75% 来自审美与表达，25% 来自技术可用性；如果画面有明确艺术意图，可以保留技术不完美带来的氛围价值。
- 光影是否均匀不是固定好坏标准，可能是摄影风格或叙事手段。
- 请根据画面意图自行判断强反差、局部光、逆光、低调、高调、舞台光等是否服务主体、情绪和空间层次。
- 只有当光线明显削弱主体可读性、情绪表达或后期可用性时，才把它作为低分依据。
- 技术质检也要区分“风格化选择”和“失误/瑕疵”，不要机械追求平均曝光或平光。

只输出一个 JSON 对象，字段如下：
{
  "scores": {
    "overall": 0到10的数字，体现审美表达优先，不要简单平均审美和技术,
    "aesthetic": {
      "overall": 0到10的数字,
      "quality": 0到10的数字,
      "composition": 0到10的数字,
      "lighting": 0到10的数字,
      "color": 0到10的数字,
      "depth_of_field": 0到10的数字,
      "content": 0到10的数字
    },
    "technical": {
      "overall": 0到10的数字,
      "sharpness": 0到10的数字,
      "exposure": 0到10的数字,
      "contrast": 0到10的数字,
      "cleanliness": 0到10的数字
    }
  },
  "confidence": 0到1的数字,
  "title": "一句短标题",
  "summary": "图片摄影整体文本评价，两三句话概括照片优缺点",
  "explanation": "说明为什么给出这些分数，指出低分或扣分依据",
  "photography_suggestions": ["下次拍摄时可改进的建议，最多3条"],
  "retouching_suggestions": ["这张图后期修图建议，最多3条"]
}
""".strip()


def build_text_only_prompt(
    *,
    filename: str,
    score_context_lines: Sequence[str],
    prompt_text: str,
    base_prompt: str = LLM_REVIEW_USER_PROMPT,
) -> str:
    context = "\n".join(score_context_lines) if score_context_lines else "- 暂无可用前置评分。"
    return "\n\n".join(
        [
            base_prompt,
            "当前模型没有接收图片输入。请不要声称你直接看到了照片；请基于下列本地模型评分、技术质检和文件信息，生成二次评审、扣分解释和建议。",
            f"文件名：{filename}",
            f"前置评分：\n{context}",
            prompt_text,
        ]
    )


def build_image_prompt(prompt_text: str, base_prompt: str = LLM_REVIEW_USER_PROMPT) -> str:
    return f"{base_prompt}\n\n{prompt_text}"


def build_llm_review_payload(
    *,
    model: str,
    input_mode: str,
    prompt_text: str,
    filename: str = "",
    score_context_lines: Sequence[str] = (),
    image_data_url: str = "",
    temperature: float = 0.2,
    max_tokens: int = 900,
) -> dict[str, object]:
    system_prompt = LLM_REVIEW_TEXT_SYSTEM_PROMPT if input_mode == "text" else LLM_REVIEW_SYSTEM_PROMPT
    if input_mode == "text":
        user_content: object = build_text_only_prompt(
            filename=filename,
            score_context_lines=score_context_lines,
            prompt_text=prompt_text,
        )
    else:
        user_content = [
            {"type": "text", "text": build_image_prompt(prompt_text)},
            {"type": "image_url", "image_url": {"url": image_data_url, "detail": "low"}},
        ]

    return {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }
