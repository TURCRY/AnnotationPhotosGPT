import pandas as pd
from datetime import datetime, timedelta

def parse_time(horodatage: str) -> datetime:
    try:
        return datetime.strptime(horodatage.strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return datetime.strptime("2025-01-01 " + horodatage.strip(), "%Y-%m-%d %H:%M:%S")  # fallback si format court

def extract_transcription_segment(transcription_df: pd.DataFrame, 
                                   target_time_str: str, 
                                   before_s: int, 
                                   after_s: int) -> str:
    target_time = parse_time(target_time_str)
    start_time = target_time - timedelta(seconds=before_s)
    end_time = target_time + timedelta(seconds=after_s)

    transcription_df['horodatage_dt'] = transcription_df['horodatage'].apply(parse_time)
    mask = (transcription_df['horodatage_dt'] >= start_time) & (transcription_df['horodatage_dt'] <= end_time)
    segment = transcription_df[mask].copy()
    if segment.empty:
        return "[Aucune transcription dans cette plage de temps]"
    return "\n".join([f"{row['locuteur']}: {row['texte']}" for _, row in segment.iterrows()])