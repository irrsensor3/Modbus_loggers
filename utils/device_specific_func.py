import struct
import csv
import logging
import time
import sys
from datetime import datetime
from pymodbus.client import ModbusSerialClient, ModbusTcpClient
from utils.supabase_push import push_dcm_reading

logger = logging.getLogger(__name__)



def list_regis(client: ModbusSerialClient, start_addr: int, reg_count: int, csv_file: str, device_range: range) -> None:
    """List and optionally save Modbus holding registers for one or more devices."""
    for unit_id in device_range:
        logger.info(f"[list_regis] Listing registers for device with Modbus ID = {unit_id} ...")

        try:
            response = client.read_holding_registers(address=start_addr, count=reg_count, device_id=unit_id)
            if not response or getattr(response, "isError", lambda: True)():
                logger.warning(f"[list_regis] No valid response from device {unit_id}")
                continue

            regs = response.registers
            if not regs:
                logger.warning(f"[list_regis] Incomplete response from device {unit_id}")
                continue

            logger.info(f"[list_regis] Raw registers ({len(regs)}):")

            chunk_size = 10  # how many registers per line
            for i in range(0, len(regs), chunk_size):
                chunk = regs[i:i + chunk_size]
                logger.info("[list_regis] [" + ", ".join(f"{r}" for r in chunk) + "]")

        except Exception as e:
            logger.error(f"[list_regis] Exception reading device {unit_id}: {e}")




def hoymiles_dtu_p(client: ModbusTcpClient, start_addr: int, reg_count: int,
                   csv_file: str, device_range: range) -> None:
    regs = []

    for i in device_range:
        logger.info(f"[hoymiles_dtu_p] Collecting registers for device {i} ...")
        time.sleep(0.2)  # brief pause between devices

        max_retries = 10
        attempt = 0
        success = False

        while attempt < max_retries:
            try:
                response = client.read_input_registers(
                    address=start_addr + 96 * (i - 1),
                    count=reg_count,
                    device_id=1
                )

                # Validate response
                if not response or response.isError():
                    attempt += 1
                    logger.warning(f"[hoymiles_dtu_p] Attempt {attempt}/{max_retries} failed for device {i}, retrying...")
                    time.sleep(2)
                    continue

                # Got valid data
                regs.append(response.registers + [datetime.now().strftime("%Y-%m-%dT%H:%M:%S")])
                success = True
                break  # stop retrying, move to next device

            except Exception as e:
                attempt += 1
                logger.error(f"[hoymiles_dtu_p] Exception on attempt {attempt}/{max_retries} for device {i}: {e}")
                time.sleep(2)

        if not success:
            logger.critical(f"[hoymiles_dtu_p] Failed to read device {i} after {max_retries} attempts. Shutting down system...")
            client.close()  # Close connection cleanly
            sys.exit(1)     # Exit the entire program

    # --- Parse and log data ---
    for i in device_range:
        try:
            data = regs[i - 1]

            if not isinstance(data, list) or len(data) < 41:
                logger.error(f"[hoymiles_dtu_p] Invalid data length for device {i}: {len(data)}")
                continue

            # Helper for safe division
            def safe_div(value, divisor):
                return round(value / divisor, 2) if isinstance(value, (int, float)) else None

            now = data[-1]  # timestamp
            serial_number = b''.join(struct.pack('>H', r) for r in data[0:3]).hex()
            total_prod = (data[3] << 16) + data[4]
            today_prod = (data[5] << 16) + data[6]
            temp = safe_div(data[20], 10)

            # PV1–PV4 values
            PV = {}
            for n in range(4):
                base = 21 + n * 3
                PV[f"V{n+1}"] = safe_div(data[base], 10)
                PV[f"I{n+1}"] = safe_div(data[base + 1], 100)
                PV[f"P{n+1}"] = safe_div(data[base + 2], 10)

            operating_status = data[39] if len(data) > 39 else None
            Error = "No error"

            # --- Logging values ---
            logger.info(f"[hoymiles_dtu_p] Datetime         : {now}")
            logger.info(f"[hoymiles_dtu_p] Serial Number    : {serial_number}")
            logger.info(f"[hoymiles_dtu_p] Total Prod [Wh]  : {total_prod}")
            logger.info(f"[hoymiles_dtu_p] Today Prod [Wh]  : {today_prod}")
            logger.info(f"[hoymiles_dtu_p] Temp [°C]        : {temp}")
            logger.info(f"[hoymiles_dtu_p] PV Voltage [V]   : {', '.join(str(PV[f'V{n+1}']) for n in range(4))}")
            logger.info(f"[hoymiles_dtu_p] PV Current [A]   : {', '.join(str(PV[f'I{n+1}']) for n in range(4))}")
            logger.info(f"[hoymiles_dtu_p] PV Power   [W]   : {', '.join(str(PV[f'P{n+1}']) for n in range(4))}")
            logger.info(f"[hoymiles_dtu_p] Operating Status : {operating_status}")

            # --- Write to CSV ---
            with open(csv_file, mode="a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    now, serial_number,
                    round(total_prod, 1),
                    round(today_prod, 1),
                    temp,
                    *(PV[f"V{n+1}"] for n in range(4)),
                    *(PV[f"I{n+1}"] for n in range(4)),
                    *(PV[f"P{n+1}"] for n in range(4)),
                    operating_status,
                    Error
                ])

        except IndexError as e:
            logger.error(f"[hoymiles_dtu_p] Index error while parsing data: {e}")
        except Exception as e:
            logger.error(f"[hoymiles_dtu_p] Unexpected error during parsing: {e}")



def tp_700(client: ModbusSerialClient, start_addr: int, reg_count: int, csv_file: str, device_range: range) -> None:
    for unit_id in device_range:
        logger.info(f"[tp_700] Reading temperature data logger (TP-700) with Modbus ID = {unit_id} ...")

        try:
            response = client.read_holding_registers(address=start_addr,count=reg_count,device_id=unit_id)

            # --- Validate response ---
            if not response or response.isError():
                raise ValueError(f"Invalid or no Modbus response from device {unit_id}")

            regs = response.registers
            if not regs or len(regs) < reg_count:
                raise ValueError(f"Incomplete response from device {unit_id}")

        except Exception as e:
            # Record error with None values, then exit
            now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            logger.error(f"[tp_700] Error reading device {unit_id}: {e}")
            temps = [None] * 24
            Error = "Error"

            logger.info(f"[tp_700] Datetime: {now}")
            for i in range(0, len(temps), 6):
                row = temps[i:i + 6]
                logger.info("[tp_700] " + "  ".join(f"CH{i+j+1:02d}: {t}" for j, t in enumerate(row)))

            # Write record before exit
            with open(csv_file, mode="a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([now, unit_id] + temps + [Error])

            # Close client and exit system
            client.close()
            sys.exit(1)

        # --- Log raw registers ---
        logger.info(f"[tp_700] Raw registers ({len(regs)}):")
        chunk_size = 10
        for i in range(0, len(regs), chunk_size):
            chunk = regs[i:i + chunk_size]
            logger.info("[tp_700] [" + ", ".join(f"{r}" for r in chunk) + "]")

        # --- Decode 24 temperature channels (big endian) ---
        try:
            temps = []
            for i in range(0, reg_count, 2):
                high = regs[i]
                low = regs[i + 1]
                bytes_be = struct.pack('>HH', high, low)
                temp_c = struct.unpack('>f', bytes_be)[0]
                temps.append(temp_c)
        except Exception as e:
            # If decode fails, log and exit after recording None
            now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            logger.critical(f"[tp_700] Error decoding data for device {unit_id}: {e}")
            temps = [None] * 24
            Error = "Decode error"

            with open(csv_file, mode="a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([now, unit_id] + temps + [Error])

            client.close()
            sys.exit(1)

        # --- Normal operation ---
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        Error = "No error"
        logger.info(f"[tp_700] Datetime: {now}")
        for i in range(0, len(temps), 6):
            row = temps[i:i + 6]
            logger.info("[tp_700] " + "  ".join(f"CH{i+j+1:02d}: {t:.2f} °C" for j, t in enumerate(row)))

        # --- Write to CSV ---
        try:
            with open(csv_file, mode="a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([now, unit_id] + [round(t, 2) for t in temps] + [Error])
        except Exception as e:
            logger.critical(f"[tp_700] Failed to write to CSV: {e}")
            client.close()
            sys.exit(1)



def dcm_3366(client: ModbusSerialClient, start_addr: int, reg_count: int, csv_file: str, device_range: range) -> None:
    """Read DC meter (DCM3366) and save readings."""
    for device_id in device_range:
        logger.info(f"[dcm_3366] Reading DC meter (DCM3366) with Modbus ID = {device_id} ...")

        try:
            response = client.read_holding_registers(
                address=start_addr, count=reg_count, device_id=device_id
            )
        except Exception as e:
            logger.info(f"[dcm_3366] Exception reading device {device_id}: {e}")
            Forward_energy = Active_power = Current = Voltage = None
            Error = "Error"
            now = datetime.now().isoformat()

            logger.info(f"[dcm_3366] Datetime: {now}")
            logger.info(f"[dcm_3366] Forward energy (kWh): {Forward_energy}")
            logger.info(f"[dcm_3366] Active power (kW): {Active_power}")
            logger.info(f"[dcm_3366] Current (A): {Current}")
            logger.info(f"[dcm_3366] Voltage (V): {Voltage}")

            # Append to CSV with None values
            with open(csv_file, mode="a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([now, device_id, Forward_energy, Active_power, Current, Voltage, Error])

            # Cleanly close client before exit
            try:
                if client.is_socket_open():
                    client.close()
                    logger.info("[dcm_3366] Modbus client closed due to error.")
            except Exception as close_err:
                logger.info(f"[dcm_3366] Error while closing client: {close_err}")

            logger.info("[dcm_3366] Exiting system due to critical read error.")
            sys.exit(1)

        # === Decode normal data ===
        regs = response.registers
        logger.info(f"[dcm_3366] Raw registers ({len(regs)}):")

        chunk_size = 20
        for i in range(0, len(regs), chunk_size):
            chunk = regs[i:i + chunk_size]
            logger.info("[dcm_3366] [" + ", ".join(f"{r}" for r in chunk) + "]")

        Forward_energy = (regs[0] << 16) + regs[1]
        Active_power = (regs[20] << 16) + regs[21]
        Current = (regs[22] << 16) + regs[23]
        Voltage = (regs[24] << 16) + regs[25]
        Error = "No error"
        now = datetime.now().isoformat()

        logger.info(f"[dcm_3366] Datetime: {now}")
        logger.info(f"[dcm_3366] Forward energy (kWh): {Forward_energy / 100:.3f}")
        logger.info(f"[dcm_3366] Active power (kW): {Active_power / 1000:.3f}")
        logger.info(f"[dcm_3366] Current (A): {Current / 10000:.3f}")
        logger.info(f"[dcm_3366] Voltage (V): {Voltage / 10000:.1f}")

        with open(csv_file, mode="a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                now,
                device_id,
                round(Forward_energy / 100, 3),
                round(Active_power / 1000, 3),
                round(Current / 10000, 3),
                round(Voltage / 10000, 1),
                Error
            ])




def custom_weather(client: ModbusSerialClient, start_addr: int, reg_count: int, csv_file: str, device_range: range) -> None:
    """Read weather station data and save readings."""
    for device_id in device_range:
        logger.info(f"[custom_weather] Reading Weather Station with Modbus ID = {device_id} ...")

        try:
            response = client.read_holding_registers(
                address=start_addr, count=reg_count, device_id=device_id
            )
        except Exception as e:
            logger.info(f"[custom_weather] Exception reading device {device_id}: {e}")
            now = datetime.now().isoformat()
            logger.info(f"[custom_weather] Datetime: {now}")
            logger.info(f"[custom_weather] Error: {e}")

            with open(csv_file, mode="a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    now, device_id,
                    None, None, None, None,    # GHI, DHI, DNI, GTI
                    None, None, None, None,    # WindDir, WindSpeed, WindSpeed_2, WindSpeed_10
                    None, None, None,          # AirTemp, Humidity, AirPres
                    "Error"
                ])

            try:
                if client.is_socket_open():
                    client.close()
                    logger.info("[custom_weather] Modbus client closed due to error.")
            except Exception as close_err:
                logger.info(f"[custom_weather] Error while closing client: {close_err}")

            sys.exit(1)

        # === Decode normal data ===
        regs = response.registers
        logger.info(f"[custom_weather] Raw registers ({len(regs)}):")

        chunk_size = 20
        for i in range(0, len(regs), chunk_size):
            chunk = regs[i:i + chunk_size]
            logger.info("[custom_weather] [" + ", ".join(f"{r}" for r in chunk) + "]")

        # The order follows your XML <Point> tag definitions
        GHI         = regs[0]   # 40015
        DHI         = regs[1]   # 40016
        DNI         = regs[2]   # 40017
        GTI         = regs[3]   # 40018
        WindDir     = regs[7]   # 40022
        WindSpeed   = regs[8]   # 40023
        WindSpeed_2 = regs[9]  # 40024
        WindSpeed_10= regs[10]  # 40025
        AirTemp     = regs[30]  # 40045
        Humidity    = regs[37]  # 40052
        AirPres     = regs[43]  # 40058

        # Example scaling (assuming raw values are 0–1000 range as per XML span_high)
        # Adjust scale factors below based on actual sensor register documentation
        GHI         = GHI
        DHI         = DHI
        DNI         = DNI
        GTI         = GTI
        WindDir     = WindDir
        WindSpeed   = WindSpeed / 10.0
        WindSpeed_2 = WindSpeed_2 / 10.0
        WindSpeed_10= WindSpeed_10 / 10.0
        AirTemp     = AirTemp / 10.0
        Humidity    = Humidity / 10.0
        AirPres     = AirPres / 10.0

        Error = "No error"
        now = datetime.now().isoformat()

        logger.info(f"[custom_weather] Datetime: {now}")
        logger.info(f"[custom_weather] GHI: {GHI} W/m^2")
        logger.info(f"[custom_weather] DHI: {DHI} W/m^2")
        logger.info(f"[custom_weather] DNI: {DNI} W/m^2")
        logger.info(f"[custom_weather] GTI: {GTI} W/m^2")
        logger.info(f"[custom_weather] WindDir: {WindDir} deg")
        logger.info(f"[custom_weather] WindSpeed: {WindSpeed}")
        logger.info(f"[custom_weather] WindSpeed_2: {WindSpeed_2}")
        logger.info(f"[custom_weather] WindSpeed_10: {WindSpeed_10}")
        logger.info(f"[custom_weather] AirTemp: {AirTemp} deg_C")
        logger.info(f"[custom_weather] Humidity: {Humidity} %")
        logger.info(f"[custom_weather] AirPres: {AirPres} hPa")

        with open(csv_file, mode="a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                now,
                device_id,
                round(GHI, 2),
                round(DHI, 2),
                round(DNI, 2),
                round(GTI, 2),
                round(WindDir, 1),
                round(WindSpeed, 2),
                round(WindSpeed_2, 2),
                round(WindSpeed_10, 2),
                round(AirTemp, 1),
                round(Humidity, 1),
                round(AirPres, 1),
                Error
            ])
