# Third-party notices

FineRove is an independent project built on Octop. It is not an official Tencent Cloud or Octop product.

## Octop

- Source baseline: user-supplied `Octop-main.zip`, package version `1.0.3b3`.
- Archive SHA-256: `e58c7060226160008c8e5deb9c3f65638d1c2d13d4f2ae6029e3f38d8e8d9048`.
- Upstream: https://github.com/TencentCloud/Octop
- Copyright (c) 2026 Octop.
- License: MIT. The complete upstream license is retained in `LICENSE`; original file notices remain applicable.

The platform's `octop` Python namespace and package metadata are retained for upstream compatibility. FineRove's installed launchers use a separate runtime root. Third-party Python and JavaScript dependencies retain their respective licenses.

## YuChao / 驭潮

The financial data and NEO calculation service is a separate integration. Its current source repository identifies its license as AGPL-3.0-or-later. Core formulas and model weights are not included in this public client repository. Any later source integration requires retaining the applicable license and verifying source provenance.

The generic candle presentation in `dashboard/src/pages/Finance/MarketChart.tsx` adapts the hollow-rising/solid-falling styling from YuChao `frontend/src/pages/kline.ts` (local source inspected 2026-11-06). This adapted file retains its AGPL notice; the upstream license text is included at `licenses/YuChao-AGPL-3.0.txt`. The platform's MIT notice does not relicense this adapted source. No NEO calculation implementations were imported.
