# The bo loc v20260910_174715_328edec9

Bo loc tin hieu cua: **breakout** | khung 240 | 22 ma
Huan luyen: 2026-09-10 17:47:15 | cua so 0: train[0:10570] embargo[10570:10630] test[10630:11330]

## Cau hoi mo hinh nay tra loi

Khong phai *"nen nay nen mua khong"* - ma *"breakout vua phat tin hieu, co dang nghe khong"*.

Tren toan bo lich su, tin hieu tho cua chien luoc nay co ty le lai sau phi **0.4296** va ky vong **-0.00035** moi lenh. Hoa von doi **0.4321** (tinh tu bien do thang/thua THUC, khong tu ty le barrier).

## Ket qua tren khoi kiem dinh (chua tung thay)

| Chi so | Co bo loc | Khong loc | Nhan xao tron |
|---|---|---|---|
| Ky vong moi lenh | +0.00939 | +0.00119 | +0.00294 |
| Ty le thang | 0.5147 | 0.4474 | 0.4764 |
| Profit factor | 1.43 | 1.04 | 1.12 |
| So lenh | 68 | 599 | 191 |
| AUC | 0.581 | | 0.523 |

Nguong vao lenh: **0.4454** (hoa von 0.4309 + bien an toan)
Xac suat mo hinh du doan trai tu 0.2489 den 0.5391.

## Cong thang cap: TRUOT

```
  doi chung nhan xao     0.523          AUC <= 0.58            DAT
  lenh con lai sau loc   68/599         >= 30                  DAT
  ty le giu lai          0.114          trong [0.15, 0.90]     TRUOT
  AUC                    0.581          trong [0.52, 0.80]     DAT
  ky vong sau loc        0.0094         > 0.0005               DAT
  hon 'nghe het'         0.0094 vs 0.0012 hon >= 0.0020          DAT
  profit factor          1.43 vs 1.04   >= 1.10                DAT
  hon champion           khong co       chua co bo loc nao     BO QUA
```

## Dac trung quan trong nhat

- gia_tren_ema200          8.1%
- rsi                      7.3%
- vol_ratio                7.1%
- mom_6                    6.5%
- funding_ma               6.2%
- dc_pos                   5.6%
- ema_spread               5.6%
- vol_24                   4.9%
- bb_pos                   4.3%
- funding_z                3.6%

## Doc so nay the nao

- Cot **Khong loc** la moc so sanh that. Bo loc chi co gia tri neu cot
  **Co bo loc** hon han no - AUC dep ma ky vong khong hon thi vo dung.
- **Ty le giu lai** 0.114: giu qua it la chon vai lenh may man trong so nhieu,
  giu qua nhieu la bo loc dang lam nen.
- Cot **Nhan xao tron** phai vo dung. Neu no cung dep thi bo do da hong.
- So lenh o day khong phai so lenh cua danh muc: khong co gioi han vi the
  mo cung luc, khong co heat. No do chat luong BO LOC, khong phai loi nhuan.