"""Convert the public SPHERE R data into an auditable CSV for STEM-SCI QA.

The source package remains unchanged in ``test_data/spheredata.zip``.  The
derived file is a software-acceptance fixture, not a claim about a new study.
"""
from pathlib import Path

import pyreadr


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "test_data" / "spheredata_extracted" / "spheredata-main" / "data"
OUT = ROOT / "test_data" / "sphere_fci_quantitative.csv"


def main() -> None:
    fci = pyreadr.read_r(DATA / "FCI.rda")["FCI"]
    demo = pyreadr.read_r(DATA / "demographic.rda")["demographic"]
    key = pyreadr.read_r(DATA / "FCIkey.rda")["FCIkey"].iloc[0]
    item_cols = [f"FCI{i}" for i in range(1, 31)]
    score = (fci[item_cols] == key[item_cols].to_numpy()).sum(axis=1)
    result = demo[["STUDID", "GDR", "AGE", "FATHEDU", "MOTHEDU", "SCH", "COH"]].copy()
    result["group"] = result["GDR"].map({1.0: "gender_1", 2.0: "gender_2"}).fillna("unknown")
    result["transfer_score"] = score.astype(int)
    result["fci_percent"] = (score / 30 * 100).round(2)
    result.to_csv(OUT, index=False, encoding="utf-8")
    print(f"wrote {OUT} ({len(result)} rows)")


if __name__ == "__main__":
    main()
