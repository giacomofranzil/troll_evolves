"""Hot Strip Mill adapter: layout limits that do not apply to every mill type."""

from __future__ import annotations

from ..core.model import (
    FWD,
    KIND_COILBOX,
    MAX_COILERS,
    Case,
    Problem,
)


def validate(case: Case) -> list[Problem]:
    """HSM-only consistency: one coilbox, at most three coilers, last pass forward."""
    problems: list[Problem] = []

    def add(locator: str, message: str) -> None:
        problems.append(Problem(locator, message))

    def warn(locator: str, message: str) -> None:
        problems.append(Problem(locator, message, "warning"))

    line = case.line
    boxes = [e for e in line.equipment if e.kind == KIND_COILBOX]
    if len(boxes) > 1:
        add(
            f"equipment:{boxes[1].id}",
            "at most one coilbox is allowed in the layout",
        )

    for product in case.products:
        tag = f"product:{product.id}"
        if product.passes and product.passes[-1].direction != FWD:
            add(
                f"pass:{product.id}:{product.passes[-1].pass_no}",
                f"product {product.id}: the last pass must be in direction 'fwd', "
                "otherwise the piece keeps moving backwards and never reaches the coiler",
            )

        coilbox_filled = bool(
            product.coilbox_v_thread
            or product.coilbox_v_coil
            or product.coilbox_v_uncoil
            or product.coilbox_thread_length
            or product.coilbox_delay
        )
        if boxes and product.uses_coilbox(line):
            if product.coilbox_thread_length < 0:
                add(tag, f"product {product.id}: coilbox_thread_length_m cannot be negative")
            if product.coilbox_delay < 0:
                add(tag, f"product {product.id}: coilbox_delay_s cannot be negative")
            for name, value in (
                ("coilbox_v_thread_mps", product.coilbox_v_thread),
                ("coilbox_v_coil_mps", product.coilbox_v_coil),
                ("coilbox_v_uncoil_mps", product.coilbox_v_uncoil),
            ):
                if value < 0:
                    add(tag, f"product {product.id}: {name} cannot be negative")
        elif boxes and product.use_coilbox is False and coilbox_filled:
            warn(
                tag,
                f"product {product.id}: coilbox speeds are filled but coilbox is NO "
                "(bypass); they are ignored",
            )
        elif not boxes and product.use_coilbox is True:
            warn(
                tag,
                f"product {product.id}: coilbox is YES but there is no coilbox in the "
                "layout; the tick is ignored",
            )
        elif not boxes and coilbox_filled:
            warn(
                tag,
                f"product {product.id}: coilbox speeds are filled but there is no "
                "coilbox in the layout; they are ignored",
            )

    coilers = line.coilers
    if len(coilers) > MAX_COILERS:
        add(
            f"equipment:{coilers[MAX_COILERS].id}",
            f"at most {MAX_COILERS} coilers are allowed in the layout",
        )
    pattern = case.settings.coiler_pattern
    coiler_ids = {e.id for e in coilers}
    for cid in pattern:
        if cid not in coiler_ids:
            add(
                "setting:coiler_pattern",
                f"coiler_pattern: {cid!r} is not a coiler in the layout",
            )
    # An empty pattern is not a problem: Case.coiler_cycle falls back to every coiler.
    if len(coilers) >= 2 and pattern:
        used = set(pattern)
        if len(used) < 2:
            add(
                "setting:coiler_pattern",
                "with two or more coilers, coiler_pattern must name at least two "
                "distinct coilers. If every piece goes to one mandrel, remove the "
                "unused coilers from the layout",
            )
        for unused in sorted(coiler_ids - used):
            warn(
                f"equipment:{unused}",
                f"{unused} is in the layout but not in coiler_pattern; remove it "
                "from the layout if it is not used",
            )
    elif pattern and coilers:
        only = coilers[0].id
        for cid in pattern:
            if cid != only:
                add(
                    "setting:coiler_pattern",
                    f"coiler_pattern names {cid!r} but the only coiler is {only}",
                )

    return problems
