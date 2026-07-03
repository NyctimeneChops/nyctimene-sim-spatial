# Deployment guide — experiment day

Follow these steps in order. Do not skip ahead.

---

## 1. Connect to the Vast.ai instance

Find the IP and port on the Vast.ai dashboard under your running instance.

```
ssh -p <PORT> root@<IP>
```

Once connected, start a tmux session so processes survive if the SSH connection drops:

```
tmux new -s experiment
```

All subsequent commands run inside this tmux session. To detach without stopping anything: `Ctrl-B D`. To reattach later: `tmux attach -t experiment`.

---

## 2. Transfer the code

Run this from your **local machine** (not inside the instance):

```
scp -rP <PORT> /path/to/nyctimene_experiment root@<IP>:/root/
```

Then back inside the instance, confirm it arrived:

```
ls /root/nyctimene_experiment
```

---

## 3. Run setup

```
cd /root/nyctimene_experiment
chmod +x setup_vastai.sh
./setup_vastai.sh
```

The script will:
- Install PostgreSQL and start it
- Create the `nyctimene_ledger` database and apply `schema.sql`
- Install all Python dependencies (torch will take a few minutes)
- Write a `.env` file with `DATABASE_URL` pre-filled and two placeholder values

Expected final output:
```
=== Setup complete ===
  Edit .env, then start the experiment with: python main.py
```

If the script exits with an error, read the output and fix the cause before continuing. Re-running the script is safe.

---

## 4. Fill in `.env`

```
nano /root/nyctimene_experiment/.env
```

The file will look like this:

```
DATABASE_URL=postgresql://postgres:nyctimene@localhost:5432/nyctimene_ledger
FLASK_SECRET_KEY=REPLACE_ME
EXPERIMENT_RUN_NAME=REPLACE_ME
```

Replace the two `REPLACE_ME` values:

| Variable | What to set |
|---|---|
| `FLASK_SECRET_KEY` | Any long random string (e.g. `nyctimene-run1-2026`) |
| `EXPERIMENT_RUN_NAME` | A short label for this run (e.g. `run1`) |

`DATABASE_URL` is already correct — do not change it.

Save and exit: `Ctrl-O`, `Enter`, `Ctrl-X`.

---

## 5. Start the Flask ledger

The ledger is a separate process that must be running before `main.py` starts. Open a second tmux window:

```
Ctrl-B C
```

Start the ledger:

```
cd /root/nyctimene_experiment
python app.py
```

Expected output:
```
 * Running on http://127.0.0.1:5000
```

Leave this window running. Switch back to window 0:

```
Ctrl-B 0
```

---

## 6. Confirm the health check passes

```
curl -s http://127.0.0.1:5000/health | python3 -m json.tool
```

Expected response:
```json
{
    "database": "connected",
    "status": "ok"
}
```

**Do not proceed if `database` is anything other than `"connected"`.**

Common causes of failure:
- PostgreSQL is not running: `service postgresql start`
- `DATABASE_URL` is wrong in `.env`: check for typos
- The ledger (app.py) is not running: check tmux window 1

---

## 7. Run `main.py`

```
cd /root/nyctimene_experiment
python main.py
```

`main.py` will run its own health check, then print the experiment group configuration table, then initialize 48 models and all world nodes. This takes a few seconds.

When initialization completes you will see:

```
Experiment ready. 48 models initialized across 6 groups.
Type START to begin or anything else to abort:
```

Verify the group table looks correct before proceeding. If anything looks wrong, type anything other than `START` to abort without starting agent threads — the database will need to be reset with `python reset_db.py` before trying again.

---

## 8. Type START

```
START
```

The experiment runs for 14 in-world days. A status line prints every 60 seconds showing the current day, elapsed wall-clock time, actions completed, and survival counts per group.

```
[day 3 | 42m elapsed | 1847 actions today (1601 succeeded)]
  run1_A    [########]  8/8 alive
  run1_B    [########]  8/8 alive
  run1_C    [######..]  6/8 alive
  ...
```

---

## 9. Monitoring during the run

To check in from another terminal without interrupting the process:

```
tmux attach -t experiment
```

Switch between windows with `Ctrl-B 0` (main.py) and `Ctrl-B 1` (ledger).

To query the ledger directly:

```
curl -s http://127.0.0.1:5000/models | python3 -m json.tool
```

---

## Emergency stop

If you need to halt early, press `Ctrl-C` in the `main.py` window. The experiment handles `KeyboardInterrupt` cleanly: it signals all 48 agent threads to finish their current iteration, then prints a completion summary. The database is left intact.

To reset and start over from scratch:

```
python reset_db.py
```

Type `RESET` when prompted. Then return to step 7.

---

## Post-experiment

Do these steps after `main.py` prints the completion summary and exits.

### 1. Generate the results report

The Flask ledger must still be running. In the `main.py` tmux window:

```
cd /root/nyctimene_experiment
python analysis/experiment_report.py > results/report.txt
```

Confirm the file was written:

```
ls -lh results/report.txt
```

### 2. Download the results folder

Run this from your **local machine**:

```
scp -rP <PORT> root@<IP>:/root/nyctimene_experiment/results ./results
```

Open `results/report.txt` locally and verify it looks complete before shutting the instance down.

### 3. Shut down the Vast.ai instance

Once you have confirmed the report is on your local machine, destroy the instance from the Vast.ai dashboard. This stops billing immediately.

Do not destroy the instance before verifying the local copy — there is no way to recover the data afterward.
