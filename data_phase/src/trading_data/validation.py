from datetime import date

import numpy as np
import pandas as pd
import pyarrow as pa

REQUIRED = ['timestamp', 'symbol', 'open', 'high', 'low', 'close', 'volume']
VALIDATOR_VERSION = '0.1.0'


class DataRejected(ValueError):
    """Input cannot cross the next research boundary; no success artifact is published."""


def validate_bars(table: pa.Table, catalog, *, start: str, end: str, universe: list[str]):
    if len(table.column_names) != len(set(table.column_names)) or set(table.column_names) != set(REQUIRED):
        raise DataRejected(f'columns must be exactly {REQUIRED}; rename explicitly upstream')
    if not table.num_rows:
        raise DataRejected('empty source table')
    timestamp_type = table.schema.field('timestamp').type
    if not pa.types.is_timestamp(timestamp_type) or timestamp_type.tz != 'UTC':
        raise DataRejected('timestamp must be Arrow timestamp with timezone UTC')
    if not (pa.types.is_string(table.schema.field('symbol').type) or pa.types.is_large_string(table.schema.field('symbol').type)):
        raise DataRejected('symbol must be an Arrow string column')
    for name in REQUIRED[2:]:
        dtype = table.schema.field(name).type
        if not (pa.types.is_integer(dtype) or pa.types.is_floating(dtype)):
            raise DataRejected(f'{name} must be numeric (not string, bool, or decimal)')
    if any(table[name].null_count for name in REQUIRED):
        raise DataRejected('nulls are not allowed')
    frame = table.select(REQUIRED).to_pandas()
    if set(frame['symbol']) != set(catalog.instruments):
        raise DataRejected('source symbols do not match catalog instruments')
    if len(set(catalog.instruments)) != len(catalog.instruments):
        raise DataRejected('duplicate catalog instruments')
    if not set(universe).issubset(catalog.instruments):
        raise DataRejected('requested instrument missing from catalog')
    values = frame[REQUIRED[2:]].to_numpy(dtype='float64')
    if not np.isfinite(values).all():
        raise DataRejected('OHLCV values must be finite')
    if (frame['volume'] < 0).any():
        raise DataRejected('negative volume')
    if catalog.price_policy == 'positive' and (frame[['open', 'high', 'low', 'close']] <= 0).any().any():
        raise DataRejected('nonpositive price forbidden by catalog price policy')
    if ((frame['low'] > frame[['open', 'close']].min(axis=1)) |
        (frame['high'] < frame[['open', 'close']].max(axis=1)) |
        (frame['low'] > frame['high'])).any():
        raise DataRejected('OHLC price relationships are invalid')
    if frame.duplicated(['symbol', 'timestamp']).any():
        raise DataRejected('duplicate symbol/timestamp')
    for symbol, group in frame.groupby('symbol', sort=False):
        if not group['timestamp'].is_monotonic_increasing:
            raise DataRejected(f'unsorted timestamps for {symbol}; no silent sorting')
    width = pd.Timedelta(catalog.interval_seconds, unit='s')
    ns = frame['timestamp'].astype('datetime64[ns, UTC]').astype('int64')
    if (ns % width.value != 0).any():
        raise DataRejected('timestamps are off the epoch-aligned bar grid')
    lower = pd.Timestamp(date.fromisoformat(start), tz='UTC')
    upper = pd.Timestamp(date.fromisoformat(end), tz='UTC') + pd.Timedelta(86400, unit='s')
    selected = frame.loc[frame.symbol.isin(universe) & (frame.timestamp >= lower) & (frame.timestamp < upper)].copy()
    if set(selected.symbol) != set(universe):
        raise DataRejected('no selected rows for at least one requested instrument')
    summaries = {}
    for symbol in sorted(universe):
        group = selected.loc[selected.symbol == symbol]
        if catalog.calendar_policy == 'continuous_24x7':
            if group.iloc[0].timestamp != lower or group.iloc[-1].timestamp + width != upper:
                raise DataRejected(f'incomplete window boundaries for {symbol}')
            if not group.timestamp.diff().iloc[1:].eq(width).all():
                raise DataRejected(f'missing bars or irregular cadence for {symbol}')
        summaries[symbol] = {
            'rows': len(group), 'first_bar_open': group.iloc[0].timestamp.isoformat(),
            'last_bar_open': group.iloc[-1].timestamp.isoformat(),
        }
    selected = selected.sort_values(['symbol', 'timestamp'], kind='stable').reset_index(drop=True)
    # These are bar labels, not observation-availability guarantees.
    selected['bar_end_utc'] = selected.timestamp + width
    quality = {
        'validator_version': VALIDATOR_VERSION, 'status': 'passed',
        'source_rows': len(frame), 'selected_rows': len(selected),
        'per_symbol': summaries, 'calendar_policy': catalog.calendar_policy,
        'coverage_status': 'complete_24x7' if catalog.calendar_policy == 'continuous_24x7' else 'not_checked',
        'warnings': [] if catalog.calendar_policy == 'continuous_24x7' else ['Exchange-session completeness NOT checked'],
        'no_repair_applied': True,
        'not_checked': ['vendor_accuracy', 'point_in_time_availability', 'survivorship_bias',
                        'corporate_actions', 'futures_rolls', 'cross_source_reconciliation'],
    }
    normalized = pa.Table.from_pandas(selected, preserve_index=False)
    return normalized, quality
