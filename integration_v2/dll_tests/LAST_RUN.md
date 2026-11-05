# FARSITE DLL test results

Overall: **PASS**

DLL: `C:\Workspace\FlamMap6\farsite.dll`

Outputs: `C:\Users\gtanu\OneDrive\Desktop\Honours\integration_v2\dll_tests\outputs\20261105T162530Z_a95b55`

| Check | Result | Evidence |
| --- | --- | --- |
| 1. DLL loading and object lifecycle | PASS | Expected exports found; native object created and destroyed in a child process. |
| 2. Real fire growth and native output validation | PASS | Raw native perimeters expanded; arrival raster contains positive arrival times. |
| 3. Repeatability with identical inputs | PASS | Two independent native runs agreed on sampled shapes and the full arrival raster. |
| 4. Restart from the previous native perimeter | PASS | Native minute-2 perimeter was written as the next ignition and continued growing. |
| 5. Invalid input is rejected | PASS | A missing landscape caused an explicit worker error rather than a successful forecast. |
| 6. Inspectable plot | PASS | Saved native_results.png from measured native outputs. |

## 2. Real fire growth and native output validation

```json
{
  "initial_area_m2": 576.0,
  "native_area_samples": [
    {
      "elapsed_minutes": 1,
      "area_m2": 951.0
    },
    {
      "elapsed_minutes": 2,
      "area_m2": 1412.0
    },
    {
      "elapsed_minutes": 3,
      "area_m2": 2065.0
    },
    {
      "elapsed_minutes": 4,
      "area_m2": 2744.0
    }
  ],
  "positive_arrival_cells": 24
}
```

## 4. Restart from the previous native perimeter

```json
{
  "restart_at_controller_minute": 2,
  "carried_ignition_area_m2": 1412.0,
  "restart_native_area_samples": [
    {
      "elapsed_minutes": 1,
      "area_m2": 2006.0
    },
    {
      "elapsed_minutes": 2,
      "area_m2": 2702.0
    },
    {
      "elapsed_minutes": 3,
      "area_m2": 3523.0
    },
    {
      "elapsed_minutes": 4,
      "area_m2": 4441.0
    }
  ]
}
```

## 5. Invalid input is rejected

```json
{
  "expected_worker_exit_code": 1
}
```

These checks exercise the installed native DLL. The terrain and weather are synthetic.
A pass checks execution and data exchange; it does not establish real-world forecast accuracy.
