# The mo hinh v20260910_195826_96834d01

Huan luyen: 2026-09-10 19:58:26 | khung 240 | 22 ma
Chia khoi: train[0:10010] calib[10070:10570] val[10630:11330] (embargo = max_horizon = 60 nen)
Dau van tay bai toan: 96834d01deb9028e

## Ket qua tren khoi kiem dinh (mo hinh chua tung thay)

| Chi so | Gia tri | Nhan xao tron (phai ~0 ky nang) |
|---|---|---|
| AUC trung binh | 0.627 | 0.511 |
| IC cat ngang | 0.0777 | -0.0055 |
| t-stat IC (da hieu chinh) | 2.61 | -0.16 |
| t-stat IC (tho - KHONG dung de ket luan) | 7.68 | |
| Ky vong moi lenh | 0.0000 | 0.0255 |
| Profit factor | 0.00 | 2.09 |
| So lenh | 0 | 2 |
| Ty le vao lenh | 0.000 | |

## Cong thang cap: TRUOT

```
  doi chung nhan xao     0.511          AUC <= 0.55            DAT
  mau kiem dinh          782            hieu dung >= 300       DAT
  so moc do IC           699            moc >= 30              DAT
  AUC trung binh         0.627          trong [0.52, 0.75]     DAT
  IC cat ngang           0.0777         >= 0.010               DAT
  t-stat cua IC          2.61           >= 2.0                 DAT
  so lenh tren val       0              >= 50                  TRUOT
  ky vong moi lenh       0.0000         > 0.0005 sau phi       TRUOT
  profit factor          0.00           >= 1.15                TRUOT
  ty le vao lenh         0.000          <= 0.35                DAT
  hon champion           khong co       chua co mo hinh nao    BO QUA
```

## Dac trung quan trong nhat (chieu mua)

- rsi                      46.3%
- ema_spread               13.7%
- funding_ma               10.7%
- bb_pos                   9.1%
- dc_pos                   8.5%
- atr_pct_r                2.6%
- gia_tren_ema200          2.0%
- mom_6                    1.5%
- vol_24                   1.2%
- mom_72                   1.2%

## Doc so nay the nao

- AUC 0.50 = khong biet gi. 0.52-0.56 la muc thuc te tren du lieu gia.
  Tren 0.75 gan nhu chac chan la ro ri chu khong phai ky nang.
- Hai dong t-stat: ban THO gia dinh cac moc thoi gian doc lap, dieu do SAI
  vi nhan keo dai 60 nen nen cac moc canh nhau chong lan nhau.
  Chenh lech giua hai dong chinh la muc do mot bao cao ngay tho se noi doi.
  Cong thang cap chi dung ban da hieu chinh.
- Cot 'nhan xao tron' la doi chung: mo hinh huan luyen tren nhan da xao.
  No PHAI vo dung. Neu no cung dep thi bo do da hong.
- 'Ky vong moi lenh' da tru phi taker va slippage ca hai chieu.
- So lenh o day KHONG phai so lenh cua danh muc: khong co gioi han vi the
  mo cung luc. No do chat luong nguon tin hieu, khong phai loi nhuan cuoi.