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

        const activeAlerts = this.alerts.filter(alert => this.isAlertActive(alert));

        // Set modal content
        document.getElementById('modal_lg_close_title').textContent = i18n.t('weather_alerts.section_title');
        const modalBody = document.getElementById('modal_lg_close_body');
        DOMUtils.clear(modalBody);

        const wrapper = document.createElement('div');
        wrapper.className = 'weather-alerts-modal-body';

        if (activeAlerts.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'modal-no-alerts';
            empty.textContent = i18n.t('weather_alerts.no_alerts');
            wrapper.appendChild(empty);
        } else {
            activeAlerts.forEach((alert) => {
                const alertTime = new Date(alert.time);
                const iconClass = this.getAlertTypeIcon(alert.type);

                const card = document.createElement('div');
                card.className = `alert alert-${alert.severity === 'HIGH' ? 'danger' : 'warning'}`;
                card.setAttribute('role', 'alert');

                const title = document.createElement('div');
                title.className = 'fw-bold';

                const iconSpan = document.createElement('span');
                iconSpan.appendChild(DOMUtils.createIcon(iconClass, 'icon-inline'));
                const typeSpan = document.createElement('span');
                typeSpan.textContent = ` ${this.getAlertTypeLabel(alert.type)}`;
                const timeSpan = document.createElement('span');
                timeSpan.textContent = ` ${alertTime.toLocaleString()}`;

                title.appendChild(iconSpan);
                title.appendChild(typeSpan);
                title.appendChild(timeSpan);

                const message = document.createElement('div');
                message.textContent = alert.message || '';

                card.appendChild(title);
                card.appendChild(message);
                wrapper.appendChild(card);
            });
        }

        modalBody.appendChild(wrapper);

        const bs_modal = new bootstrap.Modal('#modal_lg_close', {
            backdrop: 'static',
            focus: true,
            keyboard: true
        });

        bs_modal.show();
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

    getAlertTypeLabel(type) {
        const keyMap = {
            DEW_WARNING: 'weather_alerts.alert_dew_warning',
            WIND_WARNING: 'weather_alerts.alert_wind_warning',
            SEEING_WARNING: 'weather_alerts.alert_seeing_warning',
            TRANSPARENCY_WARNING: 'weather_alerts.alert_transparency_warning',
        };
        const key = keyMap[type];
        if (key) {
            return i18n.t(key);
        }
        return String(type || '').replaceAll('_', ' ');
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
    }
}

// Auto-initialize
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initWeatherAlerts);
} else {
    initWeatherAlerts();
}

// Export for global use
window.weatherAlertsSystem = weatherAlertsSystem;
window.initWeatherAlerts = initWeatherAlerts;