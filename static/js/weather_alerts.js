// ======================
// Weather Alerts & Notifications System
// ======================

/**
 * Weather alerts notification system for astrophotography
 */
class WeatherAlertsSystem {
    constructor() {
        this.alerts = [];
        this.notificationContainer = null;
        this.updateInterval = null;
        this.isInitialized = false;
        
        this.init();
    }
    
    init() {
        this.createNotificationContainer();
        this.startPeriodicCheck();
        this.isInitialized = true;
        //console.log('Weather alerts system initialized');
    }
    
    createNotificationContainer() {
        // Create notification container if it doesn't exist
        this.notificationContainer = document.getElementById('weather-notifications');
        if (!this.notificationContainer) {
            this.notificationContainer = document.createElement('li');
            this.notificationContainer.id = 'weather-notifications';
            this.notificationContainer.className = 'nav-item';
            // Add this element to first of ul id="end-navbar"
            const endNavbar = document.getElementById('end-navbar');
            if (endNavbar) {
                endNavbar.insertBefore(this.notificationContainer, endNavbar.firstChild);
            } 

        }
    }
    
    async checkForAlerts() {
        try {
            const currentLang = (typeof i18n !== 'undefined' && typeof i18n.getCurrentLanguage === 'function')
                ? i18n.getCurrentLanguage()
                : 'en';
            const data = await fetchJSONWithRetry(`/api/weather/alerts?lang=${encodeURIComponent(currentLang)}`, {}, {
                maxAttempts: 3,
                baseDelayMs: 1000,
                maxDelayMs: 8000,
                timeoutMs: 10000
            });
            
            if (data.error) {
                console.warn('Failed to fetch weather alerts:', data.error);
                return;
            }
            
            const newAlerts = data.alerts || [];
            //console.log('Fetched weather alerts:', newAlerts);
            this.processNewAlerts(newAlerts);
            
        } catch (error) {
            console.error('Error checking for weather alerts:', error);
        }
    }
    
    processNewAlerts(newAlerts) {
        // Update alerts array
        this.alerts = newAlerts;
        
        // Update header alert indicator
        this.updateHeaderAlertIndicator();
    }
    
    isAlertActive(alert) {
        // An alert is active if:
        // - It starts within the next 6 hours (future alert)
        // - OR it started within the last 3 hours (recent alert still relevant)
        const alertTime = new Date(alert.time);
        const now = new Date();
        const sixHoursFromNow = new Date(now.getTime() + 6 * 60 * 60 * 1000);
        const threeHoursAgo = new Date(now.getTime() - 3 * 60 * 60 * 1000);
        
        return alertTime <= sixHoursFromNow && alertTime >= threeHoursAgo;
    }
    
    updateHeaderAlertIndicator() {
        //Empty id weather-notifications
        let container = document.getElementById('weather-notifications');
        clearContainer(container);
        container.className = 'nav-item';

        const activeAlerts = this.alerts.filter(alert => this.isAlertActive(alert));

        if (activeAlerts.length > 0) {
            //console.log('Active weather alerts:', activeAlerts);

            let indicator = document.createElement('a');
            indicator.id = 'weather-alert-indicator';
            indicator.className = 'nav-link';
            indicator.onclick = () => this.showAlertsModal();
            container.appendChild(indicator);

            const totalCount = activeAlerts.length;
            const highestSeverity = this.getHighestSeverity(activeAlerts);
            const indicatorStyle = this.getIndicatorStyleBySeverity(highestSeverity);
            
            indicator.replaceChildren();
            indicator.appendChild(DOMUtils.createIcon(`bi bi-exclamation-triangle-fill ${indicatorStyle.iconClass}`, 'icon-inline'));
            indicator.appendChild(document.createTextNode(`${totalCount}`));
            
            container.className = `nav-item ${indicatorStyle.containerClass}`;
            indicator.title = `${totalCount} weather alert(s) - Click to view details`;

        } 
    }

    getHighestSeverity(alerts) {
        const severityOrder = { HIGH: 3, MEDIUM: 2, LOW: 1 };
        return alerts.reduce((currentMax, alert) => {
            const maxScore = severityOrder[currentMax] || 0;
            const alertScore = severityOrder[alert.severity] || 0;
            return alertScore > maxScore ? alert.severity : currentMax;
        }, 'LOW');
    }

    getIndicatorStyleBySeverity(severity) {
        switch (severity) {
            case 'HIGH':
                return {
                    containerClass: 'weather-alert-indicator-high-priority',
                    iconClass: 'text-danger'
                };
            case 'MEDIUM':
                return {
                    containerClass: 'weather-alert-indicator-medium-priority',
                    iconClass: 'text-warning'
                };
            case 'LOW':
                return {
                    containerClass: 'weather-alert-indicator-low-priority',
                    iconClass: 'text-info'
                };
            default:
                return {
                    containerClass: 'weather-alert-indicator-normal',
                    iconClass: 'text-warning'
                };
        }
    }
    
    showAlertsModal() {

        // Most severe first, then soonest first within the same severity
        const severityRank = { HIGH: 0, MEDIUM: 1, LOW: 2 };
        const activeAlerts = this.alerts
            .filter(alert => this.isAlertActive(alert))
            .slice()
            .sort((a, b) => {
                const rankDiff = (severityRank[a.severity] ?? 3) - (severityRank[b.severity] ?? 3);
                return rankDiff !== 0 ? rankDiff : new Date(a.time) - new Date(b.time);
            });

        // Set modal content (dedicated lightweight modal - title is static in the template)
        const modalBody = document.getElementById('weather-alerts-modal-body');
        DOMUtils.clear(modalBody);

        if (activeAlerts.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'weather-alerts-empty';
            empty.appendChild(DOMUtils.createIcon('bi bi-check-circle-fill'));
            const emptyText = document.createElement('div');
            emptyText.textContent = i18n.t('weather_alerts.no_alerts');
            empty.appendChild(emptyText);
            modalBody.appendChild(empty);
        } else {
            activeAlerts.forEach((alert) => {
                modalBody.appendChild(this.buildAlertItem(alert));
            });
        }

        const bs_modal = new bootstrap.Modal('#weather-alerts-modal', {
            focus: true,
            keyboard: true
        });

        bs_modal.show();
    }

    /** Build a single alert card for the modal (icon + severity badge + relative time + message). */
    buildAlertItem(alert) {
        const severityModifier = alert.severity === 'HIGH' ? 'high' : (alert.severity === 'LOW' ? 'low' : 'medium');

        const item = document.createElement('div');
        item.className = `weather-alert-item weather-alert-item--${severityModifier}`;
        item.setAttribute('role', 'alert');

        const iconWrap = document.createElement('div');
        iconWrap.className = 'weather-alert-item__icon';
        iconWrap.appendChild(DOMUtils.createIcon(this.getAlertTypeIcon(alert.type)));
        item.appendChild(iconWrap);

        const content = document.createElement('div');
        content.className = 'weather-alert-item__content';

        const header = document.createElement('div');
        header.className = 'weather-alert-item__header';

        const badge = document.createElement('span');
        badge.className = 'weather-alert-item__badge';
        badge.textContent = i18n.t(`weather_alerts.alert_severity_${severityModifier}`);
        header.appendChild(badge);

        const time = document.createElement('span');
        time.className = 'weather-alert-item__time';
        time.textContent = this.formatRelativeAlertTime(new Date(alert.time));
        header.appendChild(time);

        content.appendChild(header);

        const message = document.createElement('div');
        message.className = 'weather-alert-item__message';
        message.textContent = alert.message || '';
        content.appendChild(message);

        item.appendChild(content);
        return item;
    }

    /** e.g. "In 45 min" / "In 1h 30min" / "12 min ago" */
    formatRelativeAlertTime(alertTime) {
        const diffMs = alertTime.getTime() - Date.now();
        const isPast = diffMs < 0;
        const absMinutes = Math.round(Math.abs(diffMs) / 60000);
        const hours = Math.floor(absMinutes / 60);
        const minutes = absMinutes % 60;

        const parts = [];
        if (hours > 0) parts.push(`${hours}${i18n.t('units.hour')}`);
        if (minutes > 0 || parts.length === 0) parts.push(`${minutes}${i18n.t('units.minute')}`);

        return i18n.t(isPast ? 'weather_alerts.started_ago' : 'weather_alerts.starts_in', { time: parts.join(' ') });
    }
    
    startPeriodicCheck() {
        // Check for alerts every 5 minutes
        this.updateInterval = setInterval(() => {
            this.checkForAlerts();
        }, 300000);
        
        // Initial check
        this.checkForAlerts();
    }
    
    stopPeriodicCheck() {
        if (this.updateInterval) {
            clearInterval(this.updateInterval);
            this.updateInterval = null;
        }
    }
    
    getAlertTypeIcon(type) {
        const icons = {
            'DEW_WARNING': 'bi bi-droplet-half',
            'WIND_WARNING': 'bi bi-wind',
            'SEEING_WARNING': 'bi bi-eye',
            'TRANSPARENCY_WARNING': 'bi bi-cloud-fog2',
            'CLOUD_WARNING': 'bi bi-cloud'
        };
        return icons[type] || 'bi bi-exclamation-triangle-fill';
    }

    destroy() {
        this.stopPeriodicCheck();
        if (this.notificationContainer) {
            this.notificationContainer.remove();
        }
        const indicator = document.getElementById('weather-alert-indicator');
        if (indicator) {
            indicator.remove();
        }
        this.isInitialized = false;
    }
}

// Global instance
let weatherAlertsSystem = null;

// Initialize when DOM is loaded
function initWeatherAlerts() {
    if (!weatherAlertsSystem) {
        weatherAlertsSystem = new WeatherAlertsSystem();
        window.weatherAlertsSystem = weatherAlertsSystem;
    }
}

// Auto-initialize
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initWeatherAlerts);
} else {
    initWeatherAlerts();
}

// Export for global use
window.initWeatherAlerts = initWeatherAlerts;