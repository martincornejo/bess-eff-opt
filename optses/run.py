import os
import time
import logging
import multiprocessing
from functools import partial
from datetime import timedelta

from tqdm import tqdm
from concurrent.futures import ProcessPoolExecutor, as_completed

from mpc import run_mpc


## logger
class MultiprocessingFileHandler(logging.Handler):
    def __init__(self, filename, lock):
        super().__init__()
        self.filename = filename
        self.lock = lock

    def emit(self, record):
        log_entry = self.format(record)
        with self.lock:  # Use the global lock
            with open(self.filename, "a") as f:
                f.write(log_entry + "\n")


def setup_logger(lock):
    logger = logging.getLogger("MultiprocessingLogger")
    logger.setLevel(logging.INFO)

    handler = MultiprocessingFileHandler("simulation.log", lock)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)

    logger.addHandler(handler)
    return logger


## multiprocess
def run_scenario(scenario, queue, lock) -> None:
    name, params = scenario
    log = setup_logger(lock)
    slot = queue.get()  # progress bar position

    try:
        start_time = time.time()  # start timer
        tqdm_options = {"position": slot, "mininterval": 1.0, "leave": False}
        df = run_mpc(name, tqdm_options=tqdm_options, **params)
        df.index.name = "time"
        df.to_parquet(f"results/{name}.parquet")

        # log
        elapsed_time = time.time() - start_time
        hours, rem = divmod(elapsed_time, 3600)
        minutes, seconds = divmod(rem, 60)
        log.info(f"Simulation {name} finished in {int(hours):02}:{int(minutes):02}:{int(seconds):02}.")
    except Exception as e:
        log.error(f"Simulation {name} failed with {type(e).__name__}: {e}")
    finally:
        queue.put(slot)  # free progress bar position


def run_parallel(scenarios: dict) -> None:
    workers = os.cpu_count()

    with multiprocessing.Manager() as manager:
        # Initialize the queue with available slots for a progress bar.
        # We start at 1 since position 0 tracks the overall progress.
        queue = manager.Queue()
        for i in range(1, workers + 1):
            queue.put(i)

        # for logging and displaying the progress bars without race conditions
        lock = manager.RLock()

        # pass the queue and lock to the scenario runner
        run_scenario_worker = partial(run_scenario, queue=queue, lock=lock)

        pbar = tqdm(desc="Total simulations", total=len(scenarios))  # progress bar of all simulations
        with ProcessPoolExecutor(workers, initializer=tqdm.set_lock, initargs=(lock,)) as pool:
            futures = [pool.submit(run_scenario_worker, scenario) for scenario in scenarios.items()]
            for future in as_completed(futures):
                pbar.update(1)


## scenarios
def main():
    scenarios = {}

    year = 2021

    horizon = 12  # h
    fec = 2.0 * (horizon / 24)  # 2 cycles per day

    model = "LP"
    for fec in (1.0, 2.0):
        for r in (1.0, 2.0, 3.0):
            for eff in (0.9, 0.95, 0.98):
                scenarios[f"{year} {model} {fec=} {r=} {eff=}"] = {
                    "profile_file": f"data/intraday_prices/electricity_prices_germany_{year}.csv",
                    "sim_params": {"start_soc": 0.0, "soh_r": r},
                    "opt_params": {"model": model, "eff": eff, "max_fec": fec * (horizon / 24)},
                    "horizon_hours": horizon,
                    "timestep_sec": 900,  # 15 min
                    "total_time": timedelta(weeks=4),
                }

    model = "NL"
    for fec in (1.0, 2.0):
        for r in (1.0, 2.0, 3.0):
            for r_opt in (1.0, 2.0, 3.0):
                scenarios[f"{year} {model} {fec=} {r=} {r_opt=}"] = {
                    "profile_file": f"data/intraday_prices/electricity_prices_germany_{year}.csv",
                    "sim_params": {"start_soc": 0.0, "soh_r": r},
                    "opt_params": {"model": model, "soh_r": r_opt, "max_fec": fec * (horizon / 24)},
                    "horizon_hours": horizon,
                    "timestep_sec": 900, # 15 min
                    "total_time": timedelta(weeks=4),
                }

    run_parallel(scenarios)


if __name__ == "__main__":
    main()
