function toggleTimeFields() {
    const fullDayCheckbox = document.getElementById("full_day");
    const timeFields = document.getElementsByClassName("time-field");
    for (let field of timeFields) {
        field.disabled = fullDayCheckbox.checked;
    }
}

function showAdditionalDetails() {
    const resourceSelect = document.getElementById("resource");
    const additionalDetails = document.getElementById("additional-details");
    if (resourceSelect.value) {
        additionalDetails.style.display = "block";
    } else {
        additionalDetails.style.display = "none";
    }
}
