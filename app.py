import os
import traceback

import anthropic
import gradio as gr

from router import route_user_turn
from prompts import build_prompt
from agency_ledger import create_ledger_entry, format_entry_for_panel


MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = 512
STORE_EXCERPT = True

SORAYA_WELCOME = (
    "Hi. I'm Soraya.\n\n"
    "I help with starting, structuring, and following through without doing the thinking for you.\n\n"
    "What are you working on or trying to figure out?"
)


def call_llm(system_prompt: str, user_message: str) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return (
            "[Configuration error: ANTHROPIC_API_KEY is not set. "
            "Add it as a Space Secret or local environment variable.]"
        )

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    text_blocks = [
        block.text
        for block in message.content
        if getattr(block, "type", None) == "text"
    ]
    return "\n".join(text_blocks).strip() or "[No text response returned.]"


def format_routing_panel(decision, prompt_meta: dict) -> str:
    active_cog = [k for k, v in decision.cognitive_signals.items() if v >= 0.5]
    active_risk = [k for k, v in decision.risk_signals.items() if v]
    cog_str = ", ".join(active_cog) if active_cog else "none"
    risk_str = ", ".join(active_risk) if active_risk else "none"
    rationale_lines = "\n".join(f"  - {r}" for r in decision.rationale)
    return (
        "### Routing Decision\n\n"
        f"- **Governance route:** `{decision.selected_route.value}`\n"
        f"- **Soraya mode:** `{prompt_meta['mode']}`\n"
        f"- **Router confidence:** `{decision.confidence}`\n\n"
        f"**Cognitive signals detected:** {cog_str}\n\n"
        f"**Risk signals detected:** {risk_str}\n\n"
        f"**Rationale:**\n{rationale_lines}\n\n"
        f"**User action required:**\n> {decision.user_action_required}"
    )


def format_session_summary(entry_dicts: list) -> str:
    if not entry_dicts:
        return "_No turns recorded yet._"
    n = len(entry_dicts)
    avg_dep = round(sum(e["dependency_risk_score"] for e in entry_dicts) / n, 3)
    avg_agency = round(sum(e["user_agency_score"] for e in entry_dicts) / n, 3)
    review_count = sum(1 for e in entry_dicts if e["review_required"])
    mode_counts = {}
    route_counts = {}
    for e in entry_dicts:
        mode_counts[e["soraya_mode"]] = mode_counts.get(e["soraya_mode"], 0) + 1
        route_counts[e["selected_route"]] = route_counts.get(e["selected_route"], 0) + 1
    return (
        f"**Session summary: {n} turn(s)**\n\n"
        f"- Avg dependency risk: `{avg_dep}`\n"
        f"- Avg user agency score: `{avg_agency}`\n"
        f"- Turns requiring review: `{review_count}`\n"
        f"- Mode counts: `{mode_counts}`\n"
        f"- Route counts: `{route_counts}`"
    )


def handle_turn(user_text: str, chat_history: list, ledger_state: dict) -> tuple:
    if not user_text or not user_text.strip():
        return (
            chat_history,
            "_No input detected. Type something to begin._",
            "_Waiting for first turn._",
            "_No turns yet._",
            ledger_state,
            "",
        )

    stored_entries = ledger_state.get("entries", [])
    turn_id = len(stored_entries) + 1

    try:
        decision = route_user_turn(user_text)
        prompt_meta = build_prompt(decision, user_text)
        soraya_response = call_llm(
            system_prompt=prompt_meta["system_prompt"],
            user_message=prompt_meta["user_message"],
        )
        entry = create_ledger_entry(
            decision=decision,
            user_text=user_text,
            turn_id=turn_id,
            store_text_excerpt=STORE_EXCERPT,
        )
        stored_entries = stored_entries + [entry.to_dict()]
        ledger_state = {"entries": stored_entries}
        routing_panel = format_routing_panel(decision, prompt_meta)
        ledger_panel = format_entry_for_panel(entry)
        session_summary = format_session_summary(stored_entries)
        chat_history = chat_history + [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": soraya_response},
        ]
    except Exception as e:
        error_msg = f"[Error during turn: {type(e).__name__}: {e}]"
        traceback.print_exc()
        chat_history = chat_history + [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": error_msg},
        ]
        routing_panel = "_Routing error. See Space logs._"
        ledger_panel = "_Ledger error. See Space logs._"
        session_summary = "_Session error._"

    return chat_history, routing_panel, ledger_panel, session_summary, ledger_state, ""


def reset_session() -> tuple:
    return (
        [{"role": "assistant", "content": SORAYA_WELCOME}],
        "_Routing metadata will appear here after your first message._",
        "_Agency Ledger will appear here after your first message._",
        "_No turns yet._",
        {},
        "",
    )


CSS = """
.panel-box { background: #f8f8f8; border-radius: 8px; padding: 12px; }
footer { display: none !important; }
"""

with gr.Blocks(title="Soraya — Executive Function Infrastructure") as demo:
    ledger_state = gr.State({})

    gr.Markdown(
        "## Soraya\n"
        "**Executive Function Infrastructure** · Kaleidoworks · Sprint 1 MVP\n\n"
        "_Soraya helps you start, structure, verify, and follow through. "
        "It does not make decisions for you._\n\n"
        "---"
    )

    with gr.Row():
        with gr.Column(scale=3):
            chatbot = gr.Chatbot(
                value=[{"role": "assistant", "content": SORAYA_WELCOME}],
                label="Soraya",
                height=480,
            )
            with gr.Row():
                user_input = gr.Textbox(
                    placeholder="What are you working on or trying to figure out?",
                    label="",
                    lines=2,
                    scale=5,
                    container=False,
                )
                submit_btn = gr.Button("Send", variant="primary", scale=1)
            reset_btn = gr.Button("Reset session", variant="secondary", size="sm")

        with gr.Column(scale=2):
            routing_panel = gr.Markdown(
                "_Routing metadata will appear here after your first message._",
                label="Routing Decision",
                elem_classes=["panel-box"],
            )
            gr.Markdown("---")
            ledger_panel = gr.Markdown(
                "_Agency Ledger will appear here after your first message._",
                label="Agency Ledger",
                elem_classes=["panel-box"],
            )
            gr.Markdown("---")
            session_summary = gr.Markdown("_No turns yet._", label="Session Summary")

    gr.Markdown(
        "\n---\n"
        "_Soraya is a behavioral MVP built by Kaleidoworks. "
        "It is not a therapist, clinician, crisis counselor, legal advisor, financial advisor, or HR decision-maker. "
        "Do not enter confidential, sensitive, regulated, or personally identifying information into this demo. "
        "If you are in crisis, please contact the 988 Suicide and Crisis Lifeline by calling or texting **988**._"
    )

    turn_outputs = [chatbot, routing_panel, ledger_panel, session_summary, ledger_state, user_input]

    submit_btn.click(fn=handle_turn, inputs=[user_input, chatbot, ledger_state], outputs=turn_outputs)
    user_input.submit(fn=handle_turn, inputs=[user_input, chatbot, ledger_state], outputs=turn_outputs)
    reset_btn.click(fn=reset_session, inputs=[], outputs=turn_outputs)


if __name__ == "__main__":
    demo.launch(css=CSS, ssr_mode=False)
