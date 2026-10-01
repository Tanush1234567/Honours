# Static v3 mathematical contract

Let B be the cells burning in the input. Other cells' fire states are constants.
Aircraft a have capacity Q_a, speed v_a, initial position at the depot and full
water. There are W action intervals and W+1 state boundaries, t=0,...,W.

## Position and movement

Integer row/column variables r[a,t], c[a,t] are bounded by the landscape.
For pixel dimensions sy and sx in metres:

```
distance[a,t] = sy*abs(r[a,t+1]-r[a,t]) + sx*abs(c[a,t+1]-c[a,t])
distance[a,t] <= v[a] * timestep_minutes
```

Absolute values use Gurobi ABS constraints. The distance objective is their sum.
Tanker end positions equal the depot. Scooper return is configurable.
For each aircraft pair and boundary, a disjunction requires different rows or
columns, unless both are at the shared depot. No cell-pair movement enumeration
is used. This does not enforce separation between sampled boundaries.

## Actions and water

Drop d[a,j,t] is binary, starts at a burning origin j, and lasts R intervals.
The aircraft stays at j throughout service. A refill f[a,site,t] is binary and
lasts the configured aircraft-specific duration. Only the airfield is eligible
for tankers; only configured water sources for scoopers.

At most one service is active for an aircraft in any interval. The selected
drop origin's row/column is linked to position via aggregate coordinate sums,
using grid-dimension bounds; service indicators enforce staying in position.

Let D be litres per drop, and u be the refill quantity. For a selected refill:

```
u = Q[a] - q[a,start]
1 <= u <= Q[a]
```

For an unselected refill u=0. Conservation at every boundary is:

```
q[a,t+1] = q[a,t] - D*sum(drops starting at t)
                     + sum(refills completing at t+1)
D*sum(drops starting at t) <= q[a,t]
0 <= q[a,t] <= Q[a]
```

All actions must complete by W. Thus the final interval is accounted for.
Drop volume is consumed at start and delivered at completion. The positive
service duration prevents simultaneous refill and discharge.

## Footprints and fire

A source j has a sparse map F[j,c] of nonnegative integer litres. Exact cell/hexagon
intersections bound integrals of the normalised longitudinal/lateral density:

```
rho(u,v) = lambda(u) * Normal(v; 0, lambda(u)/6) / Z
Z = maximum_width * (ramp_length + plateau_length) * erf(3/sqrt(2))
F[j,c] = floor(D * integral_over_cell_intersection(rho))
sum over in-grid cells F[j,c] <= D
```

The hexagon restricts lateral support to +/-3 sigma. The normal CDF supplies
the lateral integral; adaptive quadrature handles along-track integration,
split at polygon vertices and profile breakpoints. Rounding/boundary losses are
explicit; surviving weights are never renormalised. Only burning cells need
optimisation state variables, although replay records deposition elsewhere too.

For initially burning c, cumulative delivery L[c,0]=0 and:

```
L[c,t+1] = L[c,t] + sum(F[j,c]*d[a,j,start] for drops completing at t+1)
threshold = ceil(water_demand_l_m2 * cell_area_m2)
E[c,t] = 1 iff L[c,t] >= threshold
burning[c,t] = 1 - E[c,t]
d[a,j,t] <= 1 - E[j,t]
```

The threshold equivalence uses indicators:
`E=1 => L>=threshold`, `E=0 => L<=threshold-1`.
All deposited amounts are integer litres, so there is no ambiguous epsilon
interval. L is stored as continuous but is exactly a sum of integer-valued
deposits at integral decisions. Extinguishment is absorbing. It cannot occur
without sufficient delivered water, and burning cannot change back to unburned.

## Objective and solve status

Pass 1 minimises `sum(1-E[c,t], c in B, t=1..W)`.
Pass 2 minimises actual Manhattan travel with pass-1 objective no worse than
the best incumbent found. Both passes use a shared wall-clock solve budget and
zero requested MIP gap. The initial fire sample is fixed and excluded; the final
sample is included. This metric is explicitly a post-action discrete sample sum.

Each pass is a single-objective MILP, so ObjVal/ObjBound/MIPGap have their standard
meaning. Metrics are extracted from their actual expressions, not assumed objective
indices. `OPTIMAL` requires both passes to finish optimally. Otherwise a valid
incumbent is `FEASIBLE`, with primary/secondary statuses and bounds recorded.
No incumbent means `has_solution=false` and null objectives. Replay must match
the solver's complete fire trajectory and distance before results are accepted.

## Complexity

With A aircraft, |B| burning origins and W intervals, drop variables scale as
O(A|B|W), fire/load variables as O(|B|W+AW), and occupancy as O(A^2 W).
There is no O(A * landscape_cells^2 * W) loop. Building can still be expensive
for very large burning sets; construction time and model counts are reported.
The full bundled case requires a Gurobi licence without the small-model limit.
