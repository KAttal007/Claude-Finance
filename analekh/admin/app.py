"""Internal admin dashboard (design doc 19.3): feed health, failed jobs, validation failures,
token spend. Optional dependency (requirements-optional.txt):

    uv sync --group optional && streamlit run analekh/admin/app.py
"""

from datetime import UTC, datetime, timedelta

import pandas as pd
import streamlit as st
from sqlalchemy import func, select

from analekh.db.models import FeedItem, Filing, LlmCall
from analekh.db.session import session_scope

st.set_page_config(page_title="Analekh admin", layout="wide")
st.title("Analekh admin")
since = datetime.now(UTC) - timedelta(days=st.sidebar.slider("Days", 1, 30, 1))

with session_scope() as s:
    feeds = s.execute(
        select(
            FeedItem.feed,
            func.count(),
            func.max(FeedItem.pub_date),
            func.count().filter(FeedItem.company_id.is_(None)),
            func.count().filter(FeedItem.processed_at.is_(None)),
        )
        .where(FeedItem.pub_date >= since)
        .group_by(FeedItem.feed)
    ).all()
    failed = s.execute(
        select(Filing.id, Filing.company_id, Filing.kind, Filing.period_end, Filing.status)
        .where(Filing.status == "failed")
        .order_by(Filing.id.desc())
        .limit(200)
    ).all()
    blocked = s.execute(
        select(Filing.id, Filing.company_id, Filing.period_end, Filing.meta["validation"])
        .where(Filing.meta["blocks_auto_apply"].as_boolean().is_(True))
        .order_by(Filing.id.desc())
        .limit(200)
    ).all()
    tokens = s.execute(
        select(
            LlmCall.purpose,
            LlmCall.model,
            func.count(),
            func.sum(LlmCall.input_tokens),
            func.sum(LlmCall.output_tokens),
        )
        .where(LlmCall.created_at >= since)
        .group_by(LlmCall.purpose, LlmCall.model)
    ).all()

st.subheader("Feed health")
st.dataframe(pd.DataFrame(feeds, columns=["feed", "items", "latest", "unlinked", "unprocessed"]))
st.subheader("Failed jobs")
st.dataframe(pd.DataFrame(failed, columns=["filing", "company", "kind", "period", "status"]))
st.subheader("Validation failures blocking auto-apply")
st.dataframe(pd.DataFrame(blocked, columns=["filing", "company", "period", "validation"]))
st.subheader("Token spend")
st.dataframe(pd.DataFrame(tokens, columns=["purpose", "model", "calls", "input", "output"]))
