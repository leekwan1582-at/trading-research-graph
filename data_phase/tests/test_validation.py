"""Corruption tests intentionally alter real observations; mutations are NOT market data."""
import pandas as pd
import pyarrow as pa
import pytest

from trading_data.validation import DataRejected, validate_bars


def validate(table, catalog):
    return validate_bars(table, catalog, start='2024-01-01', end='2024-01-02', universe=['BTCUSDT'])


def test_real_data_and_utc_boundaries(table, catalog):
    output, quality = validate(table, catalog)
    assert output.num_rows == 2880
    assert quality['coverage_status'] == 'complete_24x7'
    assert str(output.schema.field('timestamp').type.tz) == 'UTC'
    assert output['bar_end_utc'][-1].as_py() == pd.Timestamp('2024-01-03', tz='UTC').to_pydatetime()
    assert quality['no_repair_applied'] is True


def test_raw_unchanged(table, catalog):
    before = table.to_pydict()
    validate(table, catalog)
    assert table.to_pydict() == before


@pytest.mark.parametrize('column', ['timestamp', 'symbol', 'open', 'volume'])
def test_missing_column(table, catalog, column):
    with pytest.raises(DataRejected, match='columns'):
        validate(table.drop([column]), catalog)


def test_extra_column(table, catalog):
    with pytest.raises(DataRejected, match='columns'):
        validate(table.append_column('future_return', pa.array([0.] * len(table))), catalog)


def test_empty(table, catalog):
    with pytest.raises(DataRejected, match='empty'):
        validate(table.slice(0, 0), catalog)


@pytest.mark.parametrize('name', ['timestamp', 'symbol', 'close', 'volume'])
def test_nulls(table, catalog, name):
    values = table[name].to_pylist()
    values[1] = None
    changed = table.set_column(table.schema.get_field_index(name), name, pa.array(values, type=table.schema.field(name).type))
    with pytest.raises(DataRejected, match='nulls'):
        validate(changed, catalog)


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf')])
def test_nonfinite_values(table, catalog, value):
    values = table['close'].to_pylist()
    values[1] = value
    changed = table.set_column(table.schema.get_field_index('close'), 'close', pa.array(values, type=pa.float64(), from_pandas=False))
    with pytest.raises(DataRejected, match='finite'):
        validate(changed, catalog)


@pytest.mark.parametrize('mutation,match', [
    ('negative_volume', 'negative volume'), ('bad_high', 'relationships'),
    ('bad_low', 'relationships'), ('zero_price', 'nonpositive'),
    ('duplicate', 'duplicate'), ('unsorted', 'unsorted'),
    ('missing_middle', 'missing bars'), ('missing_first', 'boundaries'),
    ('missing_last', 'boundaries'), ('off_grid', 'grid'),
    ('naive', 'timezone UTC'), ('wrong_timezone', 'timezone UTC'),
    ('symbol', 'symbols'), ('string_price', 'numeric'), ('bool_volume', 'numeric'),
])
def test_corruptions(table, catalog, mutation, match):
    frame = table.to_pandas()
    if mutation == 'negative_volume': frame.loc[1, 'volume'] = -1.0
    elif mutation == 'bad_high': frame.loc[1, 'high'] = frame.loc[1, 'low'] - 1
    elif mutation == 'bad_low': frame.loc[1, 'low'] = frame.loc[1, 'high'] + 1
    elif mutation == 'zero_price': frame.loc[1, 'close'] = 0
    elif mutation == 'duplicate': frame = pd.concat([frame.iloc[:2], frame.iloc[1:]], ignore_index=True)
    elif mutation == 'unsorted': frame.iloc[[1, 2]] = frame.iloc[[2, 1]].to_numpy()
    elif mutation == 'missing_middle': frame = frame.drop(index=500)
    elif mutation == 'missing_first': frame = frame.iloc[1:]
    elif mutation == 'missing_last': frame = frame.iloc[:-1]
    elif mutation == 'off_grid': frame.loc[1, 'timestamp'] += pd.Timedelta(1, unit='s')
    elif mutation == 'naive': frame['timestamp'] = frame.timestamp.dt.tz_localize(None)
    elif mutation == 'wrong_timezone': frame['timestamp'] = frame.timestamp.dt.tz_convert('Asia/Singapore')
    elif mutation == 'symbol': frame.loc[1, 'symbol'] = 'NOT_BTC'
    elif mutation == 'string_price': frame['close'] = frame.close.astype(str)
    elif mutation == 'bool_volume': frame['volume'] = True
    with pytest.raises(DataRejected, match=match):
        validate(pa.Table.from_pandas(frame, preserve_index=False), catalog)


def test_unchecked_calendar_is_not_complete(table, catalog):
    catalog = catalog.model_copy(update={'calendar_policy': 'unchecked'})
    out, report = validate(table.slice(10, 100), catalog)
    assert len(out) == 100
    assert report['coverage_status'] == 'not_checked'
    assert report['warnings']


def test_positive_policy_is_explicit_not_universal(table, catalog):
    catalog = catalog.model_copy(update={'price_policy': 'allow_nonpositive'})
    frame = table.to_pandas()
    frame[['open', 'high', 'low', 'close']] -= 1_000_000
    output, _ = validate(pa.Table.from_pandas(frame, preserve_index=False), catalog)
    assert output.num_rows == table.num_rows


def test_no_requested_symbol(table, catalog):
    with pytest.raises(DataRejected, match='missing from catalog'):
        validate_bars(table, catalog, start='2024-01-01', end='2024-01-02', universe=['ES'])


def test_no_rows_for_window(table, catalog):
    with pytest.raises(DataRejected, match='no selected rows'):
        validate_bars(table, catalog, start='2025-01-01', end='2025-01-02', universe=['BTCUSDT'])
