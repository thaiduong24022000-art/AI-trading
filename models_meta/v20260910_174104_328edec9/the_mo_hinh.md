# The bo loc v20260910_174104_328edec9

Bo loc tin hieu cua: **breakout** | khung 240 | 22 ma
Huan luyen: 2026-09-10 17:41:04 | train[0:10010] calib[10070:10570] val[10630:11330]

## Cau hoi mo hinh nay tra loi

Khong phai *"nen nay nen mua khong"* - ma *"breakout vua phat tin hieu, co dang nghe khong"*.

Tren toan bo lich su, tin hieu tho cua chien luoc nay co ty le lai sau phi **0.4296** va ky vong **-0.00035** moi lenh. Hoa von doi **0.4321** (tinh tu bien do thang/thua THUC, khong tu ty le barrier).

## Ket qua tren khoi kiem dinh (chua tung thay)

| Chi so | Co bo loc | Khong loc | Nhan xao tron |
|---|---|---|---|
| Ky vong moi lenh | +0.01781 | +0.00119 | +0.00000 |
| Ty le thang | 0.5588 | 0.4474 | 0.0000 |
| Profit factor | 2.11 | 1.04 | 0.00 |
| So lenh | 34 | 599 | 0 |
| AUC | 0.541 | | 0.537 |

Nguong vao lenh: **0.4350** (hoa von 0.4250 + bien an toan)
Xac suat mo hinh du doan trai tu 0.3133 den 0.4726.

## Cong thang cap: TRUOT

```
  doi chung nhan xao     0.537          AUC <= 0.58            DAT
  lenh con lai sau loc   34/599         >= 30                  DAT
  ty le giu lai          0.057          trong [0.15, 0.90]     TRUOT
  AUC                    0.541          trong [0.52, 0.80]     DAT
  ky vong sau loc        0.0178         > 0.0005               DAT
  hon 'nghe het'         0.0178 vs 0.0012 hon >= 0.0020          DAT
  profit factor          2.11 vs 1.04   >= 1.10                DAT
  hon champion           khong co       chua co bo loc nao     BO QUA
```

## Dac trung quan trong nhat

- ema_spread               17.7%
- vol_ratio                10.7%
- rsi                      9.5%
- gia_tren_ema200          7.8%
- dc_pos                   7.4%
- bb_pos                   4.8%
- vol_24                   4.3%
- funding_ma               4.2%
- mom_6                    3.8%
- funding_z                3.8%

## Doc so nay the nao

- Cot **Khong loc** la moc so sanh that. Bo loc chi co gia tri neu cot
  **Co bo loc** hon han no - AUC dep ma ky vong khong hon thi vo dung.
- **Ty le giu lai** 0.057: giu qua it la chon vai lenh may man trong so nhieu,
  giu qua nhieu la bo loc dang lam nen.
- Cot **Nhan xao tron** phai vo dung. Neu no cung dep thi bo do da hong.
- So lenh o day khong phai so lenh cua danh muc: khong co gioi han vi the
  mo cung luc, khong co heat. No do chat luong BO LOC, khong phai loi nhuan.