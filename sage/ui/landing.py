"""The screen before the first question: what this is, and six ways in."""

from __future__ import annotations

import html

import streamlit as st

from .state import start_new_turn
from .transcript import render_notice
from .view import View


def render(view: View) -> None:
    copy = view.copy
    st.markdown(
        f"""
        <div class="welcome">
            <h1 class="welcome-title">{html.escape(copy.welcome_title)}</h1>
            <p class="welcome-subtitle">{html.escape(copy.welcome_subtitle)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    examples = view.examples
    with st.container(key="examples"):
        for row in range(0, len(examples), 2):
            columns = st.columns(2, gap="medium")
            for offset, column in enumerate(columns):
                position = row + offset
                if position >= len(examples):
                    continue
                card = examples[position]
                with column, st.container(key=f"example-card-{position}"):
                    # No `help=`: a tooltip on a card that already says what it
                    # does is just a black box following the cursor around.
                    if st.button(
                        f"{card.icon} {card.label}",
                        key=f"example-{position}",
                        use_container_width=True,
                    ):
                        # With the attachments, like any other question. Without
                        # them, a file attached on the landing screen — where the
                        # chips do render — was cleared by the send and never seen.
                        start_new_turn(card.question, st.session_state.attachments)

    # Under the cards, where a refused starter card can be seen from.
    render_notice()
