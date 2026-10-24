# Demo kit: a judge plays victim A.H.

The story on the call can be anything (it is the victim's words). The payment must be real: Hound checks it on the live
Ethereum chain, so a made-up hash is rejected. The judge uses A.H.'s real payment from the public DOJ case
(US v. 4,340,000 Tether, N.D. Ohio 1:25-cv-00386): her largest send, 33.004190307 ETH on May 16, 2024 (Pacific time).

## Two ways for the judge to send the payment
1. **Screenshot (shows off the screenshot reader).** On their phone, open **houndhelp.vercel.app/demo/receipt.png**,
   press and hold, **Save to Photos**. Then on their case page, **Choose the picture of my payment** and pick it.
   Tested: confirmed on chain in about 2 seconds.
2. **Type it.** **I can't take a picture. Let me type it instead**, then paste the hash:

```
0x128a5f46accd0ba0f388fc6e800c2aa68a93754ecb53676e74dea0047541c029
```

## What they will see
"We found your payment", then on **See what we found**: Hound followed **101,352 USDT** of this payment, and all of it
sits in wallets **Tether froze**. Then **What to do now** and their own police report.

This is one of A.H.'s six payments. Say so, then open **How Hound works** for the whole case: all six sends,
377,185 USDT followed, and the reveal.

## Files
- `receipt-33eth.png`: the receipt image (also served at /demo/receipt.png). `receipt.html`: its source.
