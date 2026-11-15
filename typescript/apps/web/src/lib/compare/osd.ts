import OpenSeadragon from 'openseadragon';
import type { PaneView } from './scale.js';

/**
 * One Deep Zoom viewer. Image coordinates are level-0 pixels.
 * Image zoom follows OpenSeadragon 6: screen pixels per level-0 pixel.
 */
export function createViewer(element: HTMLElement, dziUrl: string): OpenSeadragon.Viewer {
	return OpenSeadragon({
		element,
		tileSources: dziUrl,
		drawer: 'canvas',
		showNavigationControl: false,
		showNavigator: true,
		navigatorPosition: 'BOTTOM_RIGHT',
		navigatorSizeRatio: 0.18,
		navigatorMaintainSizeRatio: true,
		minZoomImageRatio: 0.1,
		maxZoomPixelRatio: 4,
		visibilityRatio: 0.4,
		homeFillsViewer: true,
		animationTime: 0.25,
		springStiffness: 12,
		immediateRender: true,
		placeholderFillStyle: '#14191d',
		gestureSettingsMouse: {
			scrollToZoom: true,
			clickToZoom: false,
			dblClickToZoom: true,
			dragToPan: true,
			pinchToZoom: false,
			flickEnabled: false,
			zoomToRefPoint: true
		}
	});
}

export function readView(viewer: OpenSeadragon.Viewer): PaneView | null {
	const item = viewer.world.getItemAt(0);
	if (!item) return null;
	const zoom = viewer.viewport.getZoom(true);
	const center = viewer.viewport.getCenter(true);
	const imageZoom = item.viewportToImageZoom(zoom);
	const imageCenter = item.viewportToImageCoordinates(center, true);
	if (!Number.isFinite(imageZoom) || imageZoom <= 0) return null;
	if (!Number.isFinite(imageCenter.x) || !Number.isFinite(imageCenter.y)) return null;
	return { x: imageCenter.x, y: imageCenter.y, zoom: imageZoom };
}

export function writeView(viewer: OpenSeadragon.Viewer, view: PaneView): void {
	const item = viewer.world.getItemAt(0);
	if (!item || !(view.zoom > 0)) return;
	const viewportZoom = item.imageToViewportZoom(view.zoom);
	const viewportCenter = item.imageToViewportCoordinates(view.x, view.y, true);
	viewer.viewport.zoomTo(viewportZoom, undefined, true);
	viewer.viewport.panTo(viewportCenter, true);
	viewer.viewport.applyConstraints(true);
}

export function markerPixel(
	viewer: OpenSeadragon.Viewer,
	x: number,
	y: number
): { x: number; y: number } | null {
	const item = viewer.world.getItemAt(0);
	if (!item) return null;
	const viewportPoint = item.imageToViewportCoordinates(x, y, true);
	const pixel = viewer.viewport.pixelFromPoint(viewportPoint, true);
	if (!Number.isFinite(pixel.x) || !Number.isFinite(pixel.y)) return null;
	return { x: pixel.x, y: pixel.y };
}

export function destroyViewer(viewer: OpenSeadragon.Viewer | null): void {
	viewer?.destroy();
}
