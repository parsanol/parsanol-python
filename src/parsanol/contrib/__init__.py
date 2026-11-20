"""Runtime integrations for the constrained-decoding mask ABI (rs#530).

The modules here wire parsanol's per-step grammar masks into real
inference runtimes' logits-processor interfaces. Each import is
optional: the mask math itself runs on plain Python lists, so the
integrations are testable — and usable — without the runtime installed.
"""
