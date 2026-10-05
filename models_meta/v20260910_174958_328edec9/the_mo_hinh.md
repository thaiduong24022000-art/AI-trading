# The bo loc v20260910_174958_328edec9

Bo loc tin hieu cua: **breakout, trend_following, mean_reversion** | khung 240 | 22 ma
Huan luyen: 2026-09-10 17:49:58 | cua so 0: train[0:10570] embargo[10570:10630] test[10630:11330]

## Cau hoi mo hinh nay tra loi

Khong phai *"nen nay nen mua khong"* - ma *"breakout, trend_following, mean_reversion vua phat tin hieu, co dang nghe khong"*.

Tren toan bo lich su, tin hieu tho cua chien luoc nay co ty le lai sau phi **0.4132** va ky vong **-0.00247** moi lenh. Hoa von doi **0.4313** (tinh tu bien do thang/thua THUC, khong tu ty le barrier).

## Ket qua tren khoi kiem dinh (chua tung thay)

| Chi so | Co bo loc | Khong loc | Nhan xao tron |
|---|---|---|---|
| Ky vong moi lenh | -0.00952 | -0.00211 | -0.00266 |
| Ty le thang | 0.3061 | 0.4209 | 0.4014 |
| Profit factor | 0.66 | 0.92 | 0.89 |
| So lenh | 49 | 1012 | 147 |
| AUC | 0.592 | | 0.486 |

Nguong vao lenh: **0.4402** (hoa von 0.4302 + bien an toan)
Xac suat mo hinh du doan trai tu 0.2730 den 0.5017.

## Cong thang cap: TRUOT

```
  doi chung nhan xao     0.486          AUC <= 0.58            DAT
  lenh con lai sau loc   49/1012        >= 30                  DAT
  ty le giu lai          0.048          trong [0.15, 0.90]     TRUOT
  AUC                    0.592          trong [0.52, 0.80]     DAT
  ky vong sau loc        -0.0095        > 0.0005               TRUOT
  hon 'nghe het'         -0.0095 vs -0.0021 hon >= 0.0020          TRUOT
  profit factor          0.66 vs 0.92   >= 1.10                TRUOT
  hon champion           khong co       chua co bo loc nao     BO QUA
```

## Dac trung quan trong nhat

- rsi                      7.6%
- ema_spread               7.2%
- gia_tren_ema200          5.4%
- funding_r                5.3%
- mom_72                   5.1%
- oi_chg_24                5.0%
- la_mua                   4.8%
- vol_24                   4.7%
- funding_ma               4.7%
- adx                      4.6%

## Doc so nay the nao

- Cot **Khong loc** la moc so sanh that. Bo loc chi co gia tri neu cot
  **Co bo loc** hon han no - AUC dep ma ky vong khong hon thi vo dung.
- **Ty le giu lai** 0.048: giu qua it la chon vai lenh may man trong so nhieu,
  giu qua nhieu la bo loc dang lam nen.
- Cot **Nhan xao tron** phai vo dung. Neu no cung dep thi bo do da hong.
- So lenh o day khong phai so lenh cua danh muc: khong co gioi han vi the
  mo cung luc, khong co heat. No do chat luong BO LOC, khong phai loi nhuan.