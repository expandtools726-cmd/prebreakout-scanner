# Pre-Breakout Scanner (NSE)

Ye system do hisson mein bana hai, taaki aapke Google hosting par **koi Python backend na chalana pade**:

| Hissa | Kya karta hai | Kahan chalta hai |
|---|---|---|
| `scanner.py` | Yahoo Finance se data laata hai, pre-breakout stocks nikaalta hai, `site/data.js` banata hai | Aapka PC, ya GitHub Actions (free, auto) |
| `site/` | Static website (`index.html` + `data.js`). Filters, sort, sparkline, TradingView link | Aapka Google hosting |

## 1. Pehli baar chalana (apne PC par)

```bash
pip install -r requirements.txt
python scanner.py --demo        # nakli data se dashboard preview (internet nahi chahiye)
python scanner.py               # Yahoo se, tickers.txt ke stocks
python scanner.py --nifty500    # Yahoo se, Nifty 500
python scanner.py --bhavcopy    # NSE bhavcopy se POORA NSE universe (~2000+ stocks)
python scanner.py --bhavcopy --bse   # + BSE-only stocks bhi
```

### Bhavcopy mode (poora NSE/BSE)

- **Pehli baar slow hai** (~260 din ki files download hoti hain, 10-20 minute tak). Files `cache/bhav/` mein save hoti hain,
  isliye agli baar sirf naye din download hote hain (kuch second).
- Split/bonus ke liye price history khud adjust hoti hai (bhavcopy ke PREVCLOSE se), warna split wale stocks galat signal dete.
- SME, blacklisted, aur suspended/illiquid stocks hata diye jaate hain. BSE par jo stock NSE par bhi hai (ISIN match), wo dobara nahi aata.
- `--workers 4` default hai. Zyada karoge to NSE block kar sakta hai. Agar kuch din ka "error" warning aaye, bas dobara chalao;
  jo din cache mein aa chuke hain wo dobara nahi mangte.
- **Bhavcopy problem:** NSE/BSE kabhi URL ya format badal dete hain. Aisa ho to `bhavcopy.py` ke top ki `NSE_URLS` / `BSE_URLS`
  list mein naya URL daalo. Column names do formats (naya UDiFF aur purana) dono samjhe jaate hain.
- Bhavcopy sirf end-of-day hai, aur exchange shaam ~6-7 baje publish karta hai. Isse pehle chalaoge to aaj ka din nahi aayega.

Phir `site/index.html` browser mein khol lo.

## 2. Website Google hosting par daalna

`site/` folder ki **teeno files** upload karo: `index.html`, `data.js` (aur `data.json` agar chaho).
Hosting koi bhi ho (Firebase Hosting, Google Cloud Storage bucket, ya normal cPanel hosting), kaam karega, kyunki ye sirf static files hain.

Firebase Hosting ho to:

```bash
npm i -g firebase-tools
firebase login
firebase init hosting     # public folder = site, single-page app = No
firebase deploy
```

## 3. Roz auto-update (optional, free)

1. Is folder ko GitHub repo bana ke push karo.
2. `.github/workflows/scan.yml` pehle se hai. Ye roz **8:00 PM IST (Mon-Fri)** scan chalata hai aur `site/data.js` update karke commit kar deta hai.
3. Hosting par auto-deploy chahiye to workflow ke neeche wala Firebase block uncomment karo. Ya GitHub Pages use karo (Settings > Pages > folder `/site`), to alag hosting ki zaroorat hi nahi.

Agar auto nahi chahiye: roz shaam `python scanner.py` chalao aur sirf naya `data.js` upload kar do.

## Pre-breakout ki definition (chaaron setups)

| Setup | Rule |
|---|---|
| Consolidation + Volume dry-up | 20 din ki range <= 12% **aur** 5d avg vol / 50d avg vol <= 0.85 |
| 52W High ke paas | High se <= 5% door, close > 50DMA, 50DMA > 200DMA |
| Bollinger squeeze | BB width pichhle 120 din ke sabse kam 10% mein |
| Beaten-down base (Dhanuka type) | 52W high se >= 25% gira, 52W low se <= 20% upar, 20 din ki range <= 12%, close >= 20DMA ka 98% |

Sab par ye gates lagte hain:
- Price >= Rs 30 aur 20-din ka avg turnover >= Rs 20 lakh (illiquid/penny hatane ke liye).
- Breakout level (20-din ka high) se <= 10% door.
- Aaj 6%+ ya 5 din mein 12%+ bhaag chuke stocks hata diye jaate hain, kyunki wo pre-breakout nahi, breakout ho chuke hain.

**Score** = setups ke weight (30/25/25/20) + breakout level ke paas hone ka bonus, max 100.

Thresholds badalne ke liye `scanner.py` ke top ka `Config` class edit karo.

## Tests

```bash
pip install pytest
pytest
```

## Dhyan rakho

- Data Yahoo Finance ka **daily end-of-day** hai. Intraday (15m) signals ke liye broker API chahiye.
- yfinance unofficial hai, kabhi rate-limit ya kuch symbols ka data missing ho sakta hai. Aise symbols skip ho jaate hain.
- Ye screening tool hai, trade ki salah nahi. Pre-breakout ka matlab ye nahi ki breakout aayega, isliye stop-loss ke saath hi dekho.

---

# Live setup: PC ke bina (GoogieHost + GitHub Actions)

GoogieHost jaisi shared hosting par Python scanner nahi chalta, isliye kaam bata hua hai:

```
GitHub Actions (free cloud)  --scanner chalata hai-->  naya data.js
         |                                                  |
   "Run workflow" / schedule                         FTP se GoogieHost par upload
         ^                                                  |
   refresh.php (GoogieHost)  <--  website ka "Data refresh karo" button
```

## Ek baar ka setup (phone/laptop browser se ho jata hai)

**1. GitHub repo banao.** github.com par naya repo `prebreakout-scanner` (Public rakhoge to Actions minutes unlimited free; Private mein 2000 min/mahina free, phir bhi kaafi). Zip ki saari files upload karo (`.github/workflows/scan.yml` samet).

**2. FTP secrets daalo** (GoogieHost ke cPanel/Welcome email mein FTP details milti hain).
Repo > Settings > Secrets and variables > Actions > New repository secret:

| Name | Value |
|---|---|
| `FTP_SERVER` | jaise `ftp.aapkadomain.com` |
| `FTP_USERNAME` | FTP username |
| `FTP_PASSWORD` | FTP password |
| `FTP_DIR` | website folder, jaise `/public_html/` (agar site subfolder mein ho to `/public_html/scanner/`) |

**3. Pehla scan chalao.** Repo > Actions > "Pre-breakout scan" > Run workflow. Pehli baar 20-40 minute lagte hain (saari purani bhavcopy download hoti hai). Uske baad cache se 3-8 minute. Khatam hone par `index.html`, `data.js`, `refresh.php` GoogieHost par aa jate hain.

**4. Refresh button chalu karo** (optional, par phone se sabse aasan):
- GitHub > Settings > Developer settings > Personal access tokens > **Fine-grained tokens** > Generate. Repository access: **sirf is repo**. Permission: **Actions: Read and write**. Token copy kar lo.
- Password ka hash banao (apna naya password socho, GitHub ya hosting wala nahi):
  `python -c "import bcrypt;print(bcrypt.hashpw(b'APNA_PASSWORD', bcrypt.gensalt(prefix=b'2y')).decode())"` (pehle `pip install bcrypt`).
  PC nahi hai to koi bhi online "bcrypt generator" ($2y$ prefix) bhi chalega.
- GoogieHost File Manager mein site folder mein `refresh_config.sample.php` ko copy karke **`refresh_config.php`** naam do, aur token, repo (`username/prebreakout-scanner`), password_hash bharo. **Ye file GitHub par mat daalna.**

Ab website kholo (https://aapkadomain.com/...) > **Data refresh karo** > password > 10-25 minute baad page reload. "sirf NSE" tick karne se scan thoda tez hota hai.

Bina button ke: phone par GitHub app/website > Actions > Run workflow bhi wahi kaam karta hai.

## Dhyan rakho / possible dikkatein

- **NSE/BSE cloud IP block kar sakte hain.** Kabhi NSE GitHub ke servers se download rok deta hai. Aisa ho to Actions log mein "error" ya "0 stocks" dikhega; mujhe log bhejna, main Yahoo/alternate source par fallback laga dunga. Maine ye asli GitHub par test nahi kiya.
- **GoogieHost free plan** kabhi outgoing connection (curl) ya FTP limit karta hai. Agar button "GitHub se connect nahi hua" bataye to button chhodo aur GitHub app se "Run workflow" use karo, baki sab waise hi chalega.
- **Cache 7 din** na use hone par GitHub hata deta hai; roz ka schedule ise zinda rakhta hai. Hata bhi diya to bas ek lamba scan lagega.
- Token aur password kisi se share mat karo. Token sirf us ek repo ke Actions tak limited rakho.
