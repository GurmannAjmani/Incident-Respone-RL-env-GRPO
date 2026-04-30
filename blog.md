# Training Cybersecurity Agents to Fight Each Other — And Why That Matters

## The Problem: Cybersecurity Is an Arms Race

Imagine you're a IT security team protecting a company's digital infrastructure. Every day, attackers find new vulnerabilities to exploit, and defenders rush to patch them. This is a never ending cat and mouse game which can have grave consequences.

The challenge? **Traditional security training is often static and rigid.** Traditional security methods are very rigid and take a lot of them to adapt to the constantly improving exploitation methods used by hackers, leaving them vulnerable. 

**My goal was to improve performance of defence system by continously pitting them against a skilled attacker, who keeps on learning from the patterns of the defender**

---

## The Environment: A Digital Duel

This environment has two agents, the Attacker and the Defender. The defender is try to ensure the system isn't breached while the attacker is doing its best to breach the system. This simulates a real-life situation.

- **The Red Team (Attacker):** Tries to break into a simulated system using eight different tactics
- **The Blue Team (Defender):** Tries to protect the system using eight different countermeasures

### What Can the Attacker Do?

The red team can choose from eight offensive moves:

| Attack | What It Does | Real-World Example |
|--------|--------------|-------------------|
| **Phishing** | Tricks users into revealing passwords | "Click here to verify your email" |
| **Brute Force** | Tries thousands of password combinations | Automated login attempts |
| **Drive-By** | Exploits browser vulnerabilities | Malicious ads that install malware |
| **Ransomware** | Locks up files and demands payment | "Your data is encrypted, pay $50,000" |
| **SQL Injection** | Abuses database queries | "'; DROP TABLE users;--" |
| **Remote Code** | Runs malicious commands on the system | Takes over the server |
| **Privilege Escalation** | Upgrades from user → admin access | Gains full control |
| **Supply Chain** | Compromises software dependencies | Sneaks malware into trusted libraries |

### What Can the Defender Do?

The blue team responds with eight defensive tactics:

| Defense | What It Does | Real-World Example |
|---------|--------------|-------------------|
| **Multi-Factor Auth (MFA)** | Requires 2+ ways to prove identity | Password + phone confirmation |
| **Patch** | Fixes known vulnerabilities | Software security updates |
| **Endpoint Detection** | Monitors systems for suspicious behavior | Anti-malware that catches intrusions |
| **Backup & Restore** | Recovers from ransomware attacks | Cloud backups that save the day |
| **Web Firewall** | Blocks malicious traffic | Filters attacks before they reach servers |
| **Least Privilege** | Users only get the access they need | Regular employees can't delete databases |
| **SBOM Audit** | Checks all software dependencies | Finds sneaky malware in libraries |
| **Rotate Keys** | Changes access credentials frequently | API keys that expire and reset |

---

## The Story: From Beginner to Expert
 **We trained both teams using an AI technique called GRPO** (Group Relative Policy Optimization). GRPO forces the system to generate multiple possible rewards, compare them and choose the best one, making it "smarter".
**The core question: can GRPO teach an LLM to model an opponent's revealed strategy and adapt its actions accordingly — without ever being told explicitly what the opponent will do?**
### Phase 1: The Beginner Era

When the system started, both agents had no experience. The attacker would pick moves randomly — like a chess novice making illegal moves. The defender would respond just as poorly.

**Results from the untrained system:**
- Attacker average score: **0.14** out of 1.0 (mostly failing)
- Defender average score: **-0.84** out of 1.0 (actively making things worse!)
- Format errors: 30% of the time the defender would output complete nonsense

The inexperience was visible as both agents starting with near-random policies.
---

### Phase 2: The Race between the 2 agents begins

 **We alternated training between the two teams.**

1. Train the red team for 400 rounds
2. They get smarter at attacking
3. Re-train the blue team for 400 rounds against the new attacker
4. They adapt to the new threats
5. Repeat

Each iteration created a race to be the best between the attacker and defender:
- Attackers discovered better exploit chains
- Defenders learned which countermeasures actually worked
- Attackers found new vulnerabilities in those defenses
- Defenders adapted again

### Phase 3: The Expert Era

After training, here's what happened:

| Metric | Before Training | After Training | Improvement |
|--------|---|---|---|
| **Attacker Score** | 0.14 | **0.90** | 6.4× better |
| **Defender Score** | -0.84 | **-0.44** | 2× better |

The trained defender went from *hurting* the system to actually *protecting* it most of the time.

The trained attacker went from being poor at breaching systems to breaching systems most of the time!!!

**In this case it was clear that the Attacker won the race however we can see that the defender was also successfull in minimising the number of breachs (-0.84-->-0.44)**
---

## What Did They Actually Learn?

### The Attacker Learned Strategic Chaining
I tried to simulate a real life situation where an attacker most likely will not stop after one attack. It will follow attack after attack to exploit the system as much as possible.
Instead of random attacks, the trained attacker learned that **some attacks unlock follow-on attacks**:

```
Phishing → (credential harvested) → Ransomware or Local Privilege Escalation
SQL Injection → (database accessible) → Remote Code Execution
```

The attacker stopped wasting moves on irrelevant attacks and started combining tactics strategically.

### The Defender Learned Context-Aware Responses

Instead of always picking the same defense, the trained defender learned to:
- Recognize which attack pattern was most likely
- Pick countermeasures based on the attacker's recent moves
- Adapt strategy when health was critical vs. stable

For example: "I see the attacker has been trying Phishing a lot, and I haven't used MFA  — I should enforce MFA now."

---

## The Real-World Impact: Why This Matters

### 1. **Closes a Real Security Gap**

Most security training is static and rule-based. This system learns *emergent* defensive strategies that humans didn't  program. It discovers defensive patterns that actually work in practice.

### 2. **Trains Defenders Against Adaptive Threats**

Real attackers evolve their tactics. A system trained only against one attack type will fail when attackers switch strategies. 

### 3. **Demonstrates AI as a Sparring Partner**

This isn't just a one-player game. It shows how AI can be used to improve other systems by:
- Generating realistic attack scenarios
- Forcing defenses to adapt
- Finding edge cases and vulnerabilities

### 4. **Measurable, Quantifiable Learning**

The results aren't hand-wavy — we can show:
- Exact reward improvements (0.14 → 0.90)
- Error rate reduction (30% → 0%)
- Head-to-head performance metrics

---

## Behind the Scenes: How It Works

### The Environment Tracks Real Metrics

Each scenario has:
- **System Health** (starts at 100%, decreases with breaches)
- **Recent Attack History** (what tactics has the attacker used?)
- **Recent Defense History** (what tactics has the defender used?)
- **Hidden Weakness** (the true optimal attack for this scenario)
- **Correct Counter** (the true optimal defense for this scenario)

The agents must infer the right strategy through partial information, just like real security teams do.

### Three Turns Per Episode

Each duel lasts exactly 3 turns:
1. Attacker strikes
2. Defender responds
3. System health updates
4. (Repeat for 3 rounds)

This mimics real incident response cycles where defenders have limited time to react.

---

## The Numbers: Proof It Works

### Training Efficiency

We trained on a small 0.5B parameter model (tiny by modern standards) and still achieved:
- **90% attack success rate** (trained attacker finds the vulnerability)
- **100% format accuracy** (both agents output clean, parseable actions)
- **Emergent strategic behavior** (chaining attacks, adapting defenses)

This proves that **learning matters more than model size**. A small model trained through **strategic play(GRPO) beats the same model with no training**.

### Evaluation Results

We ran 50 test episodes with untrained vs. trained models:

**Attacker:**
- Untrained: Random attacks, 0.14 avg score
- Trained: Strategic chaining, 0.90 avg score

**Defender:**
- Untrained: Nonsensical responses, -0.84 avg score, 70% format accuracy
- Trained: Smart adaptation, -0.44 avg score, 100% format accuracy

Even the defender's "negative" score means something: the system is degraded but not destroyed. The goal isn't to have *positive* defender reward (that's hard), but to minimize damage. And we did that.

---

## The Bigger Picture

This project is a proof-of-concept for a powerful idea: **Multi-agent RL can train robust, adaptive AI systems by creating competitive scenarios.**

It works for cybersecurity. It could work for:
- Financial fraud detection (fraudster vs. detector)
- Game playing and strategic thinking

The key insight: **Learning through competition produces better, more robust agents than learning in isolation.**

---
