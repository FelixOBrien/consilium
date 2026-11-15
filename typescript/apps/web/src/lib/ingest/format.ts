const TIMESTAMP = new Intl.DateTimeFormat('en-GB', {
	day: '2-digit',
	month: 'short',
	hour: '2-digit',
	minute: '2-digit'
});

const COUNT = new Intl.NumberFormat('en-GB');

export function formatTimestamp(iso: string | null): string {
	if (!iso) return '—';
	const date = new Date(iso);
	if (Number.isNaN(date.getTime())) return '—';
	return TIMESTAMP.format(date);
}

export function formatDuration(ms: number): string {
	const seconds = Math.max(0, Math.round(ms / 1000));
	if (seconds < 60) return `${seconds}s`;
	const minutes = Math.floor(seconds / 60);
	const rest = seconds % 60;
	if (minutes < 60) return rest === 0 ? `${minutes}m` : `${minutes}m ${rest}s`;
	const hours = Math.floor(minutes / 60);
	const minuteRest = minutes % 60;
	return minuteRest === 0 ? `${hours}h` : `${hours}h ${minuteRest}m`;
}

export function formatCount(value: number | null | undefined): string {
	if (value == null) return '—';
	return COUNT.format(value);
}
