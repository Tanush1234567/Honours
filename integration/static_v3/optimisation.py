"""Compact coordinate MILP for a deterministic, fixed fire snapshot.

No raster-cell-pair enumeration. Positions are integer row/column coordinates;
actual Manhattan displacement is constrained and charged in metres. Drop and
refill actions occupy intervals, while loads/fire states live on W+1 boundaries.
"""
from dataclasses import dataclass
from pathlib import Path
import math
import time
import gurobipy as gp
from gurobipy import GRB
from .scenario import fleet


@dataclass
class BuiltModel:
    model: object
    scenario: object
    aircraft: list
    row: object
    col: object
    load: object
    drop: dict
    refill: dict
    refill_amount: dict
    extinguished: object
    cumulative: object
    burn_objective: object
    distance_objective: object
    build_seconds: float


def build_model(scenario):
    started = time.perf_counter()
    s, cfg = scenario, scenario.settings
    ac = fleet(cfg)
    W = cfg.horizon_steps
    A, T, J = range(len(ac)), range(W + 1), range(len(s.burning))
    nr, nc = s.grid.shape
    mdl = gp.Model("static_v3")
    mdl.Params.OutputFlag = int(cfg.solver_output)
    mdl.Params.Seed = cfg.solver_seed
    mdl.Params.Threads = cfg.solver_threads
    mdl.Params.MIPGap = 0.0
    row = mdl.addVars(A, T, vtype=GRB.INTEGER, lb=0, ub=nr - 1, name="row")
    col = mdl.addVars(A, T, vtype=GRB.INTEGER, lb=0, ub=nc - 1, name="col")
    load = {(a, t): mdl.addVar(vtype=GRB.INTEGER, lb=0, ub=ac[a]["capacity_l"],
                              name=f"load_{a}_{t}") for a in A for t in T}
    drop = {(a, j, t): mdl.addVar(vtype=GRB.BINARY, name=f"drop_{a}_{j}_{t}")
            for a in A for j in J for t in range(max(0, W - cfg.drop_steps + 1))}
    refill, refill_amount = {}, {}
    for a in A:
        sites = (cfg.airfield,) if ac[a]["kind"] == "tanker" else cfg.water_cells
        for site in sites:
            for t in range(max(0, W - ac[a]["refill_steps"] + 1)):
                key = (a, site, t)
                refill[key] = mdl.addVar(vtype=GRB.BINARY, name=f"refill_{a}_{site[0]}_{site[1]}_{t}")
                refill_amount[key] = mdl.addVar(vtype=GRB.INTEGER, lb=0,
                                               ub=ac[a]["capacity_l"], name=f"refill_l_{a}_{site[0]}_{site[1]}_{t}")
    ext = mdl.addVars(J, T, vtype=GRB.BINARY, name="extinguished")
    max_delivery = W * len(ac) * cfg.drop_volume_l
    cum = mdl.addVars(J, T, lb=0, ub=max_delivery, name="delivered_l")
    distance_terms = []
    active_services = {(a, t): [] for a in A for t in range(W)}
    drop_at = {(a, t): [] for a in A for t in range(W)}
    refill_completions = {(a, t): [] for a in A for t in range(1, W + 1)}
    deliveries = {(j, t): [] for j in J for t in range(1, W + 1)}
    cell_index = {cell: j for j, cell in enumerate(s.burning)}

    def at_cell(flag, a, t, cell):
        mdl.addGenConstrIndicator(flag, 1, row[a, t] == cell[0])
        mdl.addGenConstrIndicator(flag, 1, col[a, t] == cell[1])

    for a in A:
        mdl.addConstr(row[a, 0] == cfg.airfield[0], name=f"start_row_{a}")
        mdl.addConstr(col[a, 0] == cfg.airfield[1], name=f"start_col_{a}")
        mdl.addConstr(load[a, 0] == ac[a]["capacity_l"], name=f"start_full_{a}")
        if ac[a]["return_required"]:
            mdl.addConstr(row[a, W] == cfg.airfield[0], name=f"return_row_{a}")
            mdl.addConstr(col[a, W] == cfg.airfield[1], name=f"return_col_{a}")
        for t in range(W):
            dr = mdl.addVar(lb=-(nr - 1), ub=nr - 1, name=f"dr_{a}_{t}")
            dc = mdl.addVar(lb=-(nc - 1), ub=nc - 1, name=f"dc_{a}_{t}")
            ar = mdl.addVar(lb=0, ub=nr - 1, name=f"abs_dr_{a}_{t}")
            az = mdl.addVar(lb=0, ub=nc - 1, name=f"abs_dc_{a}_{t}")
            mdl.addConstr(dr == row[a, t + 1] - row[a, t])
            mdl.addConstr(dc == col[a, t + 1] - col[a, t])
            mdl.addGenConstrAbs(ar, dr)
            mdl.addGenConstrAbs(az, dc)
            distance = ar * s.georef["cell_size_y"] + az * s.georef["cell_size_x"]
            mdl.addConstr(distance <= ac[a]["speed_m_min"] * cfg.step_minutes,
                          name=f"speed_{a}_{t}")
            distance_terms.append(distance)

    # Occupancy is exclusive at sampled boundaries except the shared depot.
    # This is not continuous-path collision avoidance (see MODEL.md).
    depot = mdl.addVars(A, T, vtype=GRB.BINARY, name="at_depot")
    for a in A:
        for t in T:
            at_cell(depot[a, t], a, t, cfg.airfield)
    for a in A:
        for b in range(a + 1, len(ac)):
            for t in T:
                share = mdl.addVar(vtype=GRB.BINARY)
                mdl.addConstr(share <= depot[a, t])
                mdl.addConstr(share <= depot[b, t])
                sep = mdl.addVars(4, vtype=GRB.BINARY)
                mdl.addGenConstrIndicator(sep[0], 1, row[a, t] <= row[b, t] - 1)
                mdl.addGenConstrIndicator(sep[1], 1, row[b, t] <= row[a, t] - 1)
                mdl.addGenConstrIndicator(sep[2], 1, col[a, t] <= col[b, t] - 1)
                mdl.addGenConstrIndicator(sep[3], 1, col[b, t] <= col[a, t] - 1)
                mdl.addConstr(share + sep.sum() >= 1, name=f"occupancy_{a}_{b}_{t}")

    for (a, j, t), flag in drop.items():
        end = t + cfg.drop_steps
        origin = s.burning[j]
        mdl.addConstr(flag <= 1 - ext[j, t], name=f"drop_only_burning_{a}_{j}_{t}")
        for u in range(t, end):
            active_services[a, u].append(flag)
        drop_at[a, t].append(flag)
        for target, litres in s.footprints[origin].items():
            if target in cell_index:
                deliveries[cell_index[target], end].append(litres * flag)

    for (a, site, t), flag in refill.items():
        end = t + ac[a]["refill_steps"]
        amount = refill_amount[a, site, t]
        mdl.addConstr(amount <= ac[a]["capacity_l"] * flag)
        mdl.addConstr(amount >= flag)  # no zero-volume refill actions
        mdl.addGenConstrIndicator(flag, 1, amount == ac[a]["capacity_l"] - load[a, t])
        at_cell(flag, a, t, site)
        for u in range(t, end):
            active_services[a, u].append(flag)
        refill_completions[a, end].append(amount)

    for a in A:
        for t in range(W):
            drop_count = gp.quicksum(drop_at[a, t])
            used = cfg.drop_volume_l * drop_count
            service = mdl.addVar(vtype=GRB.BINARY, name=f"in_service_{a}_{t}")
            mdl.addConstr(service == gp.quicksum(active_services[a, t]), name=f"one_action_{a}_{t}")
            mdl.addGenConstrIndicator(service, 1, row[a, t + 1] == row[a, t])
            mdl.addGenConstrIndicator(service, 1, col[a, t + 1] == col[a, t])
            # At most one drop starts here. Aggregate its coordinates instead
            # of creating two location indicators for every target/time pair.
            aim_r = gp.quicksum(s.burning[j][0] * drop[a, j, t]
                               for j in J if (a, j, t) in drop)
            aim_c = gp.quicksum(s.burning[j][1] * drop[a, j, t]
                               for j in J if (a, j, t) in drop)
            mdl.addConstr(row[a, t] - aim_r <= (nr - 1) * (1 - drop_count))
            mdl.addConstr(row[a, t] - aim_r >= -(nr - 1) * (1 - drop_count))
            mdl.addConstr(col[a, t] - aim_c <= (nc - 1) * (1 - drop_count))
            mdl.addConstr(col[a, t] - aim_c >= -(nc - 1) * (1 - drop_count))
            mdl.addConstr(used <= load[a, t], name=f"water_available_{a}_{t}")
            mdl.addConstr(load[a, t + 1] == load[a, t] - used +
                          gp.quicksum(refill_completions[a, t + 1]), name=f"water_balance_{a}_{t}")

    for j in J:
        mdl.addConstr(ext[j, 0] == 0)
        mdl.addConstr(cum[j, 0] == 0)
        for t in range(1, W + 1):
            mdl.addConstr(cum[j, t] == cum[j, t - 1] + gp.quicksum(deliveries[j, t]))
            mdl.addConstr(ext[j, t] >= ext[j, t - 1])
            # Deposits and threshold are integer litres: exact iff, no epsilon gap.
            mdl.addGenConstrIndicator(ext[j, t], 1, cum[j, t] >= s.demand_l)
            mdl.addGenConstrIndicator(ext[j, t], 0, cum[j, t] <= s.demand_l - 1)

    burn = gp.quicksum(1 - ext[j, t] for j in J for t in range(1, W + 1))
    distance = gp.quicksum(distance_terms)
    mdl.setObjective(burn, GRB.MINIMIZE)
    mdl.update()
    # A guaranteed feasible baseline, with every aircraft parked at the depot.
    # All primary variables are provided; Gurobi completes auxiliary variables.
    for a in A:
        for t in T:
            row[a, t].Start, col[a, t].Start = cfg.airfield
            load[a, t].Start = ac[a]["capacity_l"]
    for var in list(drop.values()) + list(refill.values()) + list(refill_amount.values()):
        var.Start = 0
    for var in list(ext.values()) + list(cum.values()):
        var.Start = 0
    return BuiltModel(mdl, s, ac, row, col, load, drop, refill, refill_amount,
                      ext, cum, burn, distance, time.perf_counter() - started)


def _status(code):
    return {GRB.OPTIMAL: "OPTIMAL", GRB.INFEASIBLE: "INFEASIBLE", GRB.TIME_LIMIT: "TIME_LIMIT",
            GRB.INTERRUPTED: "INTERRUPTED", GRB.INF_OR_UNBD: "INF_OR_UNBD",
            GRB.UNBOUNDED: "UNBOUNDED"}.get(code, f"CODE_{code}")


def model_size(built):
    m = built.model
    return {"variables": m.NumVars, "binary_variables": m.NumBinVars,
            "linear_constraints": m.NumConstrs, "general_constraints": m.NumGenConstrs,
            "build_seconds": built.build_seconds}


def _extract(built):
    b, s = built, built.scenario
    W, cfg = s.settings.horizon_steps, s.settings
    routes = {ac["id"]: [{"step": t, "row": round(b.row[a, t].X),
                           "col": round(b.col[a, t].X), "water_l": round(b.load[a, t].X)}
                          for t in range(W + 1)] for a, ac in enumerate(b.aircraft)}
    actions = []
    for (a, j, t), var in b.drop.items():
        if var.X > 0.5:
            actions.append({"aircraft": b.aircraft[a]["id"], "kind": "drop",
                            "start_step": t, "end_step": t + cfg.drop_steps,
                            "row": s.burning[j][0], "col": s.burning[j][1],
                            "volume_l": cfg.drop_volume_l})
    for (a, site, t), var in b.refill.items():
        if var.X > 0.5:
            actions.append({"aircraft": b.aircraft[a]["id"], "kind": "refill",
                            "start_step": t, "end_step": t + b.aircraft[a]["refill_steps"],
                            "row": site[0], "col": site[1],
                            "volume_l": round(b.refill_amount[a, site, t].X)})
    actions.sort(key=lambda x: (x["start_step"], x["aircraft"], x["kind"]))
    predicted = [[list(cell) for j, cell in enumerate(s.burning) if b.extinguished[j, t].X > 0.5]
                 for t in range(W + 1)]
    burn = round(b.burn_objective.getValue())
    drop_actions = [x for x in actions if x["kind"] == "drop"]
    return {"has_solution": True, "routes": routes, "actions": actions,
            "predicted_extinguished": predicted, "burn_cell_steps": burn,
            "burn_cell_minutes": burn * cfg.step_minutes,
            "flight_distance_m": b.distance_objective.getValue(),
            "last_drop_start_min": max((x["start_step"] * cfg.step_minutes for x in drop_actions), default=None),
            "last_drop_completion_min": max((x["end_step"] * cfg.step_minutes for x in drop_actions), default=None)}


def solve_model(built, output_dir=None):
    """Two single-objective passes with a shared solver-time budget.

    The secondary pass cannot worsen the best primary incumbent. If the primary
    pass times out, any result is labelled feasible, never globally optimal.
    """
    b, m, cfg = built, built.model, built.scenario.settings
    out = Path(output_dir) if output_dir is not None else None
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        m.Params.LogFile = str(out / "solver.log")
        if cfg.write_model:
            m.write(str(out / "model.lp"))
    details = {"model": model_size(b), "primary_status": None, "secondary_status": None,
               "primary_bound": None, "primary_gap": None, "secondary_gap": None}
    m.Params.TimeLimit = cfg.time_limit_s * cfg.primary_time_fraction
    started = time.perf_counter()
    m.optimize()
    details["primary_status"] = _status(m.Status)
    if m.Status == GRB.INFEASIBLE and out is not None:
        m.computeIIS()
        m.write(str(out / "infeasible.ilp"))
    if m.SolCount == 0:
        return {**details, "status": details["primary_status"], "has_solution": False,
                "routes": {}, "actions": [], "burn_cell_steps": None,
                "flight_distance_m": None, "solve_seconds": time.perf_counter() - started}
    primary_optimal = m.Status == GRB.OPTIMAL
    details["primary_bound"] = float(m.ObjBound) if math.isfinite(m.ObjBound) else None
    best = _extract(b)
    burn_cap = best["burn_cell_steps"]
    remaining = cfg.time_limit_s - (time.perf_counter() - started)
    secondary_optimal = False
    if remaining > 0.05:
        saved_start = [(v, v.X) for v in m.getVars()]
        m.addConstr(b.burn_objective <= burn_cap, name="preserve_primary_incumbent")
        m.setObjective(b.distance_objective, GRB.MINIMIZE)
        for var, value in saved_start:
            var.Start = value
        m.Params.TimeLimit = remaining
        m.optimize()
        details["secondary_status"] = _status(m.Status)
        if m.SolCount:
            best = _extract(b)
            gap = float(m.MIPGap)
            details["secondary_gap"] = gap if math.isfinite(gap) else None
            secondary_optimal = m.Status == GRB.OPTIMAL
    bound, value = details["primary_bound"], best["burn_cell_steps"]
    if bound is not None:
        details["primary_gap"] = max(0.0, (value - bound) / max(1.0, abs(value)))
    return {**details, **best,
            "status": "OPTIMAL" if primary_optimal and secondary_optimal else "FEASIBLE",
            "primary_optimal": primary_optimal, "secondary_optimal": secondary_optimal,
            "solve_seconds": time.perf_counter() - started}


def build_and_solve(scenario, output_dir=None):
    built = build_model(scenario)
    try:
        return solve_model(built, output_dir)
    finally:
        built.model.dispose()
