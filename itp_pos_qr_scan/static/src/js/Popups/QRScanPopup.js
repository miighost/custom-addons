/** @odoo-module **/

import { Component, useState, useRef, onMounted, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class QRScanPopup extends Component {
    static template = "itp_pos_qr_scan.QRScanPopup";
    static props = {
        close: { type: Function, optional: true },
        confirm: { type: Function, optional: true },
        cancel: { type: Function, optional: true },
        getPayload: { type: Function, optional: true },
        resolve: { type: Function, optional: true },
        reject: { type: Function, optional: true },
        "*": true,
    };

    setup() {
        super.setup();
        try {
            this.popup = useService("popup");
        } catch (_e) {
            try {
                this.popup = useService("dialog");
            } catch (_e2) {
                this.popup = null;
            }
        }

        try {
            this.pos = useService("pos");
        } catch (_e) {
            this.pos = (this.env && this.env.services && this.env.services.pos) || null;
        }

        this.state = useState({
            loading: true,
            active_camera: null,
            active_camera_label: "",
            videoDevices: [],
            permissionState: "pending", // 'pending' | 'granted' | 'denied' | 'error'
            permissionError: "",
            scannedSuccess: false,
        });

        this.videoElement = useRef("preview");
        this.canvas = useRef("canvas");
        this.fileInput = useRef("fileInput");

        this.captureTimeout = 80; // Ultra-fast 80ms scan interval (12+ FPS) for instant sub-100ms detection
        this.stream = null;
        this.gCtx = null;
        this.isScanning = false;

        onMounted(() => {
            this.requestCameraPermission();
        });

        onWillUnmount(() => {
            this.stopCamera();
        });
    }

    get isBrowserSupported() {
        return Boolean(
            navigator.mediaDevices &&
            navigator.mediaDevices.enumerateDevices &&
            navigator.mediaDevices.getUserMedia
        );
    }

    get activeCameraLabel() {
        if (!this.state.active_camera_label) return "Camera";
        const lbl = this.state.active_camera_label.toLowerCase();
        if (lbl.includes("back") || lbl.includes("rear") || lbl.includes("environment")) return "📷 Back Camera";
        if (lbl.includes("front") || lbl.includes("user") || lbl.includes("selfie")) return "📷 Front Camera";
        return `📷 ${this.state.active_camera_label.substring(0, 18)}`;
    }

    get isBackCamera() {
        const lbl = (this.state.active_camera_label || "").toLowerCase();
        return lbl.includes("back") || lbl.includes("rear") || lbl.includes("environment");
    }

    playBeepSound() {
        try {
            const AudioCtx = window.AudioContext || window.webkitAudioContext;
            if (!AudioCtx) return;
            const ctx = new AudioCtx();
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = "sine";
            osc.frequency.setValueAtTime(850, ctx.currentTime); // 850Hz POS barcode beep tone
            gain.gain.setValueAtTime(0.35, ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.16);
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start();
            osc.stop(ctx.currentTime + 0.16);
        } catch (_e) {}
    }

    vibrateDevice() {
        if (navigator.vibrate) {
            try {
                navigator.vibrate([150]); // 150ms haptic feedback pulse
            } catch (_e) {}
        }
    }

    stopCamera() {
        this.state.active_camera = false;
        this.isScanning = false;
        if (this.stream) {
            try {
                this.stream.getTracks().forEach((track) => track.stop());
            } catch (_e) {}
            this.stream = null;
        }
    }

    async onClickCancel() {
        this.stopCamera();
        if (this.props && typeof this.props.close === "function") {
            this.props.close();
        } else if (this.props && typeof this.props.cancel === "function") {
            this.props.cancel();
        }
    }

    async requestCameraPermission() {
        if (!this.isBrowserSupported) {
            this.state.loading = false;
            this.state.permissionState = "error";
            this.state.permissionError = "Camera API is not accessible. Please allow camera permissions in your browser bar or access via HTTPS.";
            return;
        }

        this.state.loading = true;
        this.state.permissionError = "";

        try {
            const tempStream = await navigator.mediaDevices.getUserMedia({ audio: false, video: true });
            tempStream.getTracks().forEach((track) => track.stop());

            this.state.permissionState = "granted";
            const devices = await navigator.mediaDevices.enumerateDevices();
            const video_devices = devices.filter((d) => d.kind === "videoinput");

            this.state.videoDevices = video_devices;
            let deviceId = video_devices.length ? video_devices[0].deviceId : false;
            let facingMode = false;

            for (const device of video_devices) {
                if (device.label && device.label.toLowerCase().includes("back")) {
                    deviceId = device.deviceId;
                    facingMode = "environment";
                }
            }

            const active_camera_id = this.pos && this.pos.db ? this.pos.db.load("active_camera_id", false) : false;
            if (active_camera_id && video_devices.some((d) => d.deviceId === active_camera_id)) {
                deviceId = active_camera_id;
                facingMode = false;
            }

            this.state.loading = false;
            await this.startWebCam(deviceId, facingMode);
        } catch (error) {
            console.error("Camera permission error:", error);
            this.state.loading = false;
            this.state.permissionState = "denied";
            if (error.name === "NotAllowedError" || error.name === "PermissionDeniedError") {
                this.state.permissionError = "Camera permission was denied. Please click 'Allow' in your browser location bar.";
            } else if (error.name === "NotFoundError" || error.name === "DevicesNotFoundError") {
                this.state.permissionError = "No camera device was found on this system.";
            } else {
                await this.startWebCam(false, false);
            }
        }
    }

    async toggleCameraFacing() {
        if (!this.state.videoDevices || this.state.videoDevices.length <= 1) return;
        const currentIdx = this.state.videoDevices.findIndex(d => d.deviceId === this.state.active_camera);
        const nextIdx = (currentIdx + 1) % this.state.videoDevices.length;
        const nextDevice = this.state.videoDevices[nextIdx];
        if (nextDevice) {
            await this.onClickCameraButton(nextDevice.deviceId);
        }
    }

    async onClickCameraButton(deviceId) {
        const device = this.state.videoDevices.find(d => d.deviceId === deviceId);
        this.state.active_camera_label = device ? (device.label || "Camera") : "Camera";
        await this.startWebCam(deviceId, false);
        if (this.pos && this.pos.db) {
            this.pos.db.save("active_camera_id", deviceId);
        }
    }

    async read(result) {
        if (!result) return;

        // 1. Audio Beep + Mobile Haptic Vibration + Visual Success Flash
        this.playBeepSound();
        this.vibrateDevice();
        this.state.scannedSuccess = true;

        this.stopCamera();

        const cleanCode = String(result).trim();
        const pos = this.pos || window.posmodel || (this.env && this.env.services && this.env.services.pos);

        if (pos && typeof pos.handle_scanned_barcode === "function") {
            await pos.handle_scanned_barcode(cleanCode);
        } else if (pos) {
            const order = typeof pos.get_order === "function" ? pos.get_order() : null;
            if (order && pos.db) {
                let partner = pos.db.get_partner_by_barcode ? pos.db.get_partner_by_barcode(cleanCode) : null;
                if (!partner && pos.db.get_partners_list) {
                    const partners = pos.db.get_partners_list() || [];
                    partner = partners.find(
                        (p) =>
                            (p.barcode && String(p.barcode).trim() === cleanCode) ||
                            (p.ref && String(p.ref).trim() === cleanCode) ||
                            (p.phone && String(p.phone).trim() === cleanCode) ||
                            (p.id && String(p.id) === cleanCode)
                    );
                }
                if (partner) {
                    if (typeof order.set_partner === "function") order.set_partner(partner);
                    else if (typeof order.setPartner === "function") order.setPartner(partner);
                    else order.partner = partner;
                }
            }
        }

        if (this.env && this.env.bus) {
            try {
                this.env.bus.trigger("qr_scanned", cleanCode);
            } catch (_e) {}
        }

        if (this.props && typeof this.props.confirm === "function") {
            this.props.confirm({ confirmed: true, payload: cleanCode });
        } else if (this.props && typeof this.props.close === "function") {
            this.props.close();
        }
    }

    async startWebCam(deviceId, facingMode) {
        this.stopCamera();
        this.state.loading = false;

        if (typeof window.qrcode !== "undefined") {
            window.qrcode.callback = (value) => this.read(value);
        }

        let stream = null;
        let lastError = null;

        const constraintsList = [];
        if (deviceId) {
            constraintsList.push({
                video: {
                    deviceId: { exact: deviceId },
                    width: { ideal: 1920, min: 640 },
                    height: { ideal: 1080, min: 480 },
                },
                audio: false,
            });
            constraintsList.push({ video: { deviceId: { ideal: deviceId } }, audio: false });
        }
        if (facingMode) {
            constraintsList.push({
                video: {
                    facingMode: facingMode,
                    width: { ideal: 1920, min: 640 },
                    height: { ideal: 1080, min: 480 },
                },
                audio: false,
            });
        }
        constraintsList.push({
            video: {
                facingMode: { ideal: "environment" },
                width: { ideal: 1920, min: 640 },
                height: { ideal: 1080, min: 480 },
            },
            audio: false,
        });
        constraintsList.push({ video: true, audio: false });

        for (const constraint of constraintsList) {
            try {
                stream = await navigator.mediaDevices.getUserMedia(constraint);
                if (stream) break;
            } catch (err) {
                lastError = err;
            }
        }

        if (stream) {
            this.stream = stream;
            this.state.permissionState = "granted";
            this.state.active_camera = deviceId || true;

            const videoTrack = stream.getVideoTracks()[0];
            if (videoTrack && videoTrack.label) {
                this.state.active_camera_label = videoTrack.label;
            } else if (this.state.videoDevices.length > 0) {
                const found = this.state.videoDevices.find(d => d.deviceId === deviceId);
                this.state.active_camera_label = found ? (found.label || "Camera") : "Camera";
            }

            this.isScanning = true;
            this.success(stream);
            setTimeout(() => this.captureToCanvas(), this.captureTimeout);
        } else {
            console.error("Camera start error:", lastError);
            this.state.permissionState = "error";
            this.state.permissionError = (lastError && lastError.message)
                ? lastError.message
                : "Could not start camera feed. Please allow camera access in your browser location bar.";
        }
    }

    success(stream) {
        if (this.videoElement && this.videoElement.el) {
            this.videoElement.el.srcObject = stream;
            try {
                this.videoElement.el.play();
            } catch (_e) {}
        }
    }

    async captureToCanvas() {
        if (!this.state.active_camera || !this.isScanning) return;

        try {
            const videoEl = this.videoElement && this.videoElement.el;
            if (videoEl && videoEl.readyState === videoEl.HAVE_ENOUGH_DATA) {
                const w = videoEl.videoWidth || 800;
                const h = videoEl.videoHeight || 600;
                this.initCanvas(w, h);

                // 1. Hardware accelerated BarcodeDetector API (Supports EAN-13, Code 128, Code 39, UPC, QR)
                if ("BarcodeDetector" in window) {
                    try {
                        const formats = ["qr_code", "ean_13", "ean_8", "code_128", "code_39", "upc_a", "upc_e", "data_matrix"];
                        const detector = new window.BarcodeDetector({ formats });
                        const barcodes = await detector.detect(videoEl);
                        if (barcodes && barcodes.length > 0 && barcodes[0].rawValue) {
                            await this.read(barcodes[0].rawValue);
                            return;
                        }
                    } catch (_err) {}
                }

                // 2. Native un-distorted Canvas + jsqrcode fallback
                if (this.gCtx) {
                    this.gCtx.drawImage(videoEl, 0, 0, w, h);
                    if (typeof window.qrcode !== "undefined") {
                        window.qrcode.decode();
                    }
                }
            }
        } catch (e) {
            // ignore frame decode error
        }

        if (this.state.active_camera && this.isScanning) {
            setTimeout(() => this.captureToCanvas(), this.captureTimeout);
        }
    }

    initCanvas(w, h) {
        if (!this.canvas || !this.canvas.el) return;
        const gCanvas = this.canvas.el;
        if (gCanvas.width !== w || gCanvas.height !== h) {
            gCanvas.style.width = w + "px";
            gCanvas.style.height = h + "px";
            gCanvas.width = w;
            gCanvas.height = h;
        }
        const gCtx = gCanvas.getContext("2d", { willReadFrequently: true });
        if (gCtx) {
            this.gCtx = gCtx;
        }
    }

    triggerFileInput() {
        if (this.fileInput && this.fileInput.el) {
            this.fileInput.el.click();
        }
    }

    async onFileSelected(ev) {
        const file = ev.target.files && ev.target.files[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = (e) => {
            const img = new Image();
            img.onload = async () => {
                const w = img.width || 800;
                const h = img.height || 600;
                this.initCanvas(w, h);
                if (this.gCtx) {
                    this.gCtx.drawImage(img, 0, 0, w, h);

                    // 1. Hardware accelerated BarcodeDetector
                    if ("BarcodeDetector" in window) {
                        try {
                            const formats = ["qr_code", "ean_13", "ean_8", "code_128", "code_39", "upc_a", "upc_e", "data_matrix"];
                            const detector = new window.BarcodeDetector({ formats });
                            const barcodes = await detector.detect(img);
                            if (barcodes && barcodes.length > 0 && barcodes[0].rawValue) {
                                await this.read(barcodes[0].rawValue);
                                return;
                            }
                        } catch (_err) {}
                    }

                    // 2. jsqrcode fallback
                    if (typeof window.qrcode !== "undefined") {
                        window.qrcode.decode();
                    }
                }
            };
            img.src = e.target.result;
        };
        reader.readAsDataURL(file);
    }
}
