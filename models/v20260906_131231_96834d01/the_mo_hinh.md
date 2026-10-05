# The mo hinh v20260906_131231_96834d01

Huan luyen: 2026-09-06 13:12:31 | khung 240 | 22 ma
Chia khoi: train[0:10010] calib[10070:10570] val[10630:11330] (embargo = max_horizon = 60 nen)
Dau van tay bai toan: 96834d01deb9028e

## Ket qua tren khoi kiem dinh (mo hinh chua tung thay)

| Chi so | Gia tri | Nhan xao tron (phai ~0 ky nang) |
|---|---|---|
| AUC trung binh | 0.624 | 0.514 |
| IC cat ngang | 0.0741 | -0.0018 |
| t-stat IC | 7.15 | -0.19 |
| Ky vong moi lenh | 0.0000 | 0.0000 |
| Profit factor | 0.00 | 0.00 |
| So lenh | 0 | 0 |
| Ty le vao lenh | 0.000 | |

## Cong thang cap: TRUOT

```
  doi chung nhan xao     0.514          AUC <= 0.55            DAT
  mau kiem dinh          782            hieu dung >= 300       DAT
  so moc do IC           699            moc >= 30              DAT
  AUC trung binh         0.624          trong [0.52, 0.75]     DAT
  IC cat ngang           0.0741         >= 0.010               DAT
  t-stat cua IC          7.15           >= 2.0                 DAT
  so lenh tren val       0              >= 50                  TRUOT
  ky vong moi lenh       0.0000         > 0.0005 sau phi       TRUOT
  profit factor          0.00           >= 1.15                TRUOT
  ty le vao lenh         0.000          <= 0.35                DAT
  hon champion           khong co       chua co mo hinh nao    BO QUA
```

## Dac trung quan trong nhat (chieu mua)

- rsi                      36.5%
- bb_pos                   21.7%
- ema_spread               10.2%
- funding_ma               7.4%
- dc_pos                   6.2%
- gia_tren_ema200          6.1%
- adx                      4.7%
- mom_72                   2.5%
- atr_pct_r                1.3%
- vol_24                   1.2%

## Doc so nay the nao

- AUC 0.50 = khong biet gi. 0.52-0.56 la muc thuc te tren du lieu gia.
  Tren 0.75 gan nhu chac chan la ro ri chu khong phai ky nang.
- Cot 'nhan xao tron' la doi chung: mo hinh huan luyen tren nhan da xao.
  No PHAI vo dung. Neu no cung dep thi bo do da hong.
- 'Ky vong moi lenh' da tru phi taker va slippage ca hai chieu.
- So lenh o day KHONG phai so lenh cua danh muc: khong co gioi han vi the
  mo cung luc. No do chat luong nguon tin hieu, khong phai loi nhuan cuoi.