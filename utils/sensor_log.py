import csv
import datetime
import os

WEEK = datetime.timedelta(days=7)
WRITE_INTERVAL_S = 60
CSV_HEADER = [
    "Timestamp",
    "Bay1_C", "Bay2_C", "Bay3_C", "Bay4_C",
    "Bay1_RH", "Bay2_RH", "Bay3_RH", "Bay4_RH",
]


def get_sensor_log_path(config_service) -> str:
    """Lives beside whatever config.json the app was given - same
    "wherever this run's own data lives" scoping ConfigService already
    uses, so tests writing to a temp work_dir never touch the real
    user_data_dir() and don't collide with each other."""
    return os.path.join(os.path.dirname(config_service.path), "sensor_log.csv")


class SensorLogWriter:
    """Weekly-rotating CSV log of BAY1-4 temperature/humidity readings -
    direct port of sensor_log.c, minus the background-Windows-service
    sharing it also handles (sdr_app is a single process; there's no
    separate service to agree on a file path with)."""

    def __init__(self, config_service):
        self.config = config_service
        self._week_start = None
        saved = self.config.get("sensor_log_week_start")
        if saved:
            try:
                self._week_start = datetime.datetime.fromisoformat(saved)
            except ValueError:
                self._week_start = None
        if self._week_start is None:
            self._start_new_week()
        # First row lands ~WRITE_INTERVAL_S after construction, not
        # immediately - same throttle main.c's own tick counter gives
        # sensor_log_append_row().
        self._last_write = datetime.datetime.now()

    def _start_new_week(self):
        path = get_sensor_log_path(self.config)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", newline="") as f:
            csv.writer(f).writerow(CSV_HEADER)
        self._week_start = datetime.datetime.now()
        self.config.set("sensor_log_week_start", self._week_start.isoformat())
        self.config.save()

    def tick(self, units):
        now = datetime.datetime.now()
        if now - self._week_start >= WEEK:
            self._start_new_week()
        if (now - self._last_write).total_seconds() < WRITE_INTERVAL_S:
            return
        self._last_write = now
        self._append_row(now, units)

    def _append_row(self, now, units):
        temps, hums = [], []
        for unit in units:
            if unit.has_reading:
                temps.append(f"{unit.temperature_c:.1f}")
                hums.append(f"{unit.humidity_pct:.1f}")
            else:
                temps.append("")
                hums.append("")
        row = [now.strftime("%Y-%m-%d %H:%M:%S")] + temps + hums
        path = get_sensor_log_path(self.config)
        with open(path, "a", newline="") as f:
            csv.writer(f).writerow(row)


def read_highest_temp_rows(config_service) -> list[tuple[str, float, int]]:
    """Every logged row's own peak across its 4 bay readings (skipping
    any bay blank that tick - see SensorLogWriter._append_row()),
    sorted highest-first. Direct port of on_highest_temp_log_clicked()'s
    own CSV parse/sort (main.c) - same "a real 0.0C reading should
    still be able to win" rule (checks has-a-value, not truthiness)."""
    path = get_sensor_log_path(config_service)
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, newline="") as f:
        reader = csv.reader(f)
        next(reader, None)  # header
        for record in reader:
            if len(record) < 5:
                continue
            timestamp = record[0]
            peak = None
            peak_bay = 0
            for i in range(4):
                cell = record[1 + i].strip()
                if cell == "":
                    continue
                try:
                    value = float(cell)
                except ValueError:
                    continue
                if peak is None or value > peak:
                    peak = value
                    peak_bay = i
            if peak is not None:
                rows.append((timestamp, peak, peak_bay))
    rows.sort(key=lambda r: r[1], reverse=True)
    return rows
