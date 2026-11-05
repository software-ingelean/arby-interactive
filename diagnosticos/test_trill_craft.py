import time
from app.hardware.trill_lib import TrillLib

TRILL_BUS = 1
TRILL_ADDR = 0x30

trill = TrillLib(TRILL_BUS, "craft", TRILL_ADDR)

trill.setMode("DIFF")
trill.setPrescaler(6)
trill.setNoiseThreshold(0.01)

print("No tocar el sensor. Calibrando baseline...")
time.sleep(1)
trill.updateBaseLine()
time.sleep(1)
print("Listo. Toca un pad a la vez.")

def get_channel_value(ch):
    try:
        return float(trill.getRawData(ch))
    except Exception:
        pass

    try:
        return float(trill.rawData[ch])
    except Exception:
        pass

    try:
        return float(trill.rawData(ch))
    except Exception:
        pass

    return 0.0

while True:
    trill.readTrill()

    values = []

    for ch in range(30):
        value = get_channel_value(ch)
        values.append((ch, value))

    values.sort(key=lambda x: x[1], reverse=True)

    best_ch, best_value = values[0]

    if best_value > 0.05:
        print(f"Canal más fuerte: {best_ch} | valor: {best_value:.5f}")

    time.sleep(0.05)
