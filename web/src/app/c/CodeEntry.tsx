"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import styles from "./code.module.css";

/** Six letters or digits, read out on the phone. Lowercase and spaces are forgiven; 0/O/1/I are never issued. */
const CODE = /^[A-Z0-9]{6}$/;

export default function CodeEntry() {
  const router = useRouter();
  const [raw, setRaw] = useState("");
  const code = raw.toUpperCase().replace(/[^A-Z0-9]/g, "");
  const ok = CODE.test(code);
  return (
    <form
      className={styles.form}
      onSubmit={(e) => {
        e.preventDefault();
        if (ok) router.push(`/my/${code}`);
      }}
    >
      <label htmlFor="case-code" className={styles.label}>
        Your case code
      </label>
      <input
        id="case-code"
        className={styles.input}
        value={raw}
        onChange={(e) => setRaw(e.target.value)}
        placeholder="K7M2PQ"
        autoComplete="off"
        autoCapitalize="characters"
        spellCheck={false}
        inputMode="text"
        maxLength={8}
        aria-invalid={raw.length > 0 && !ok}
      />
      <p className={styles.hint}>Six letters or digits. The person on the phone reads it to you twice.</p>
      <button type="submit" className={styles.go} disabled={!ok}>
        Open my case
      </button>
      <p className={styles.safe}>We will never ask for your password, your PIN, or your recovery words.</p>
    </form>
  );
}
