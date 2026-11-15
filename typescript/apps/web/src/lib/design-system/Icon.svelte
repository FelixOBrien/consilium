<script lang="ts">
	import {
		Activity,
		ArrowLeft,
		ArrowRight,
		ChevronDown,
		ChevronRight,
		CircleUserRound,
		Copy,
		Database,
		Download,
		ExternalLink,
		FileText,
		Grid2X2,
		Layers3,
		MessageSquareText,
		Microscope,
		Minus,
		MoreHorizontal,
		PanelRight,
		Plus,
		ScanSearch,
		Search,
		Send,
		Sparkles,
		SquareDashedMousePointer,
		SlidersHorizontal,
		TriangleAlert,
		X,
		ZoomIn,
		ZoomOut
	} from '@lucide/svelte';

	type IconName =
		| 'activity'
		| 'annotation'
		| 'arrow-left'
		| 'arrow-right'
		| 'chevron-down'
		| 'chevron-right'
		| 'close'
		| 'copy'
		| 'database'
		| 'evidence'
		| 'external'
		| 'filter'
		| 'grid'
		| 'heatmap'
		| 'ingest'
		| 'layers'
		| 'minus'
		| 'more'
		| 'panel'
		| 'plus'
		| 'report'
		| 'search'
		| 'send'
		| 'slide'
		| 'spark'
		| 'user'
		| 'warning'
		| 'zoom-in'
		| 'zoom-out';

	let { name, size = 'md' }: { name: IconName; size?: 'sm' | 'md' | 'lg' } = $props();

	const iconMap = {
		activity: Activity,
		annotation: MessageSquareText,
		'arrow-left': ArrowLeft,
		'arrow-right': ArrowRight,
		'chevron-down': ChevronDown,
		'chevron-right': ChevronRight,
		close: X,
		copy: Copy,
		database: Database,
		evidence: ScanSearch,
		external: ExternalLink,
		filter: SlidersHorizontal,
		grid: Grid2X2,
		heatmap: SquareDashedMousePointer,
		ingest: Download,
		layers: Layers3,
		minus: Minus,
		more: MoreHorizontal,
		panel: PanelRight,
		plus: Plus,
		report: FileText,
		search: Search,
		send: Send,
		slide: Microscope,
		spark: Sparkles,
		user: CircleUserRound,
		warning: TriangleAlert,
		'zoom-in': ZoomIn,
		'zoom-out': ZoomOut
	};

	const IconComponent = $derived(iconMap[name]);
	const pixelSize = $derived(size === 'sm' ? 14 : size === 'lg' ? 24 : 18);
</script>

<IconComponent size={pixelSize} strokeWidth={1.8} aria-hidden="true" />
