// Main application logic

// Tab switching
function openTab(tabName) {
    // Hide all tab contents
    const tabContents = document.querySelectorAll('.tab-content');
    tabContents.forEach(content => {
        content.classList.remove('active');
    });

    // Remove active class from all buttons
    const tabButtons = document.querySelectorAll('.tab-button');
    tabButtons.forEach(button => {
        button.classList.remove('active');
    });

    // Show selected tab
    document.getElementById(tabName).classList.add('active');

    // Add active class to clicked button
    event.target.classList.add('active');
}

// Load quota information
async function loadQuota() {
    try {
        const response = await fetch('/api/quota');
        const data = await response.json();

        if (response.ok) {
            document.getElementById('quota-info').innerHTML = `
                Available: ${data.available_quota} / ${data.total_quota}
                (Used: ${data.used_quota})
            `;
        } else {
            showError(`Failed to load quota: ${data.message}`);
        }
    } catch (error) {
        showError(`Error loading quota: ${error.message}`);
    }
}

// Load history
async function loadHistory() {
    try {
        const response = await fetch('/api/history?page=1&page_size=20');
        const data = await response.json();

        if (response.ok) {
            displayHistory(data);
        } else {
            showError(`Failed to load history: ${data.message}`);
        }
    } catch (error) {
        showError(`Error loading history: ${error.message}`);
    }
}

function displayHistory(data) {
    const historyList = document.getElementById('history-list');

    if (!data.data || data.data.length === 0) {
        historyList.innerHTML = '<p>No history found.</p>';
        return;
    }

    let html = '<div class="history-grid">';

    data.data.forEach(item => {
        html += `
            <div class="history-item">
                <p><strong>Prompt:</strong> ${item.prompt}</p>
                <p><strong>Status:</strong> ${item.status}</p>
                <p><strong>Created:</strong> ${new Date(item.created_at).toLocaleString()}</p>
                ${item.file_url ? `<a href="${item.file_url}" target="_blank">View Video</a>` : ''}
            </div>
        `;
    });

    html += '</div>';
    historyList.innerHTML = html;
}

// Text to video form submission
document.getElementById('text-to-video-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const formData = {
        prompt: document.getElementById('prompt').value,
        aspect_ratio: document.getElementById('aspect-ratio').value,
        number_of_videos: parseInt(document.getElementById('num-videos').value)
    };

    // Show progress, hide result and error
    document.getElementById('progress').style.display = 'block';
    document.getElementById('result').style.display = 'none';
    document.getElementById('error').style.display = 'none';
    document.getElementById('progress-text').textContent = 'Initializing...';
    document.getElementById('progress-fill').style.width = '0%';

    // Create SSE connection
    const eventSource = new EventSource(
        '/api/video/text-to-video?' + new URLSearchParams({
            prompt: formData.prompt,
            aspect_ratio: formData.aspect_ratio,
            number_of_videos: formData.number_of_videos
        })
    );

    eventSource.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);

            // Update progress
            if (data.status === 'processing') {
                const progress = data.process_percentage || 0;
                document.getElementById('progress-fill').style.width = progress + '%';
                document.getElementById('progress-text').textContent =
                    `Processing: ${progress}%`;
            }

            // Handle completion
            if (data.status === 'completed') {
                eventSource.close();
                document.getElementById('progress').style.display = 'none';
                displayResult(data);
            }

            // Handle failure
            if (data.status === 'failed' || data.error) {
                eventSource.close();
                document.getElementById('progress').style.display = 'none';
                showError(data.error || 'Video generation failed');
            }

        } catch (error) {
            console.error('Error parsing SSE data:', error);
        }
    };

    eventSource.onerror = (error) => {
        console.error('SSE Error:', error);
        eventSource.close();
        document.getElementById('progress').style.display = 'none';
        showError('Connection error. Please try again.');
    };
});

function displayResult(data) {
    const resultContainer = document.getElementById('result');
    const resultContent = document.getElementById('result-content');

    let html = '<div class="result-item">';

    if (data.file_url) {
        html += `
            <video controls width="640">
                <source src="${data.file_url}" type="video/mp4">
                Your browser does not support the video tag.
            </video>
            <p><a href="${data.file_url}" target="_blank">Open in new tab</a></p>
        `;
    }

    html += `<p><strong>Video ID:</strong> ${data.id || 'N/A'}</p>`;
    html += '</div>';

    resultContent.innerHTML = html;
    resultContainer.style.display = 'block';

    // Reload quota
    loadQuota();
}

function showError(message) {
    const errorContainer = document.getElementById('error');
    errorContainer.innerHTML = `
        <div class="error-box">
            <strong>Error:</strong> ${message}
            <button onclick="this.parentElement.parentElement.style.display='none'">×</button>
        </div>
    `;
    errorContainer.style.display = 'block';
}

// Load quota on page load
document.addEventListener('DOMContentLoaded', () => {
    loadQuota();
});
