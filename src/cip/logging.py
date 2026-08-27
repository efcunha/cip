"""Logging estruturado (structlog) com mascaramento básico de PII."""

from __future__ import annotations

import logging
import re

import structlog

from cip.config import get_settings

# Padrões simples para mascarar dados sensíveis em logs de prompt (LGPD/GDPR).
_PII_PATTERNS = [
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "<email>"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<aws-access-key>"),
    (re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"), "<cpf>"),
]


def mask_pii(text: str) -> str:
    for pattern, repl in _PII_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def configure_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", level=level)
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
    )


def get_logger(name: str = "cip") -> structlog.BoundLogger:
    return structlog.get_logger(name)
