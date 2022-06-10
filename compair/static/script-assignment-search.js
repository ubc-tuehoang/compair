let api_url = "/api/assignment/search/enddate";

const options = { year: 'numeric', month: 'short', day: 'numeric' };
var searchDay = new Date().toLocaleDateString('en-us', options);

function formatDate(date) {
    var d = (new Date(date.toString().replace(/-/g, '\/')) );
    return d.toLocaleDateString('en-ca', options);
}

function getObject(object)
{
    searchDay = formatDate(object.value.toString());
    strURL = api_url.concat('?compare_end=').concat(object.value);
    getsearchapi(strURL);
}

// Defining async function
async function getsearchapi(url) {

    // Storing response
    const response = await fetch(url);

    // Storing data in form of JSON
    var search_data = await response.json();
    //console.log(search_data);
    if (response) {
        hideloadersearch();
    }
    showsearchapi(search_data);
}

// Function to hide the loader
function hideloadersearch() {
    document.getElementById('loading').style.display = 'none';
}
// Function to define innerHTML for HTML table
function showsearchapi(search_data) {

    let tab = `<tr>
          <th>Assignment Name</th>
          <th>Answering Begins</th>
          <th>Answering Ends</th>
          <th>Comparing Begins</th>
          <th>Comparing Ends</th>
         </tr>`;


    var iKey = 0;
    for (let key in  search_data) {
        //tab += `<tr><td colspan="4">${search_data[key]}</td></tr>`;
        let obj = JSON.parse(search_data[key])
        tab += `<tr><td>${JSON.stringify(obj.name).replace(/\"/g, "")}</td><td>${JSON.stringify(obj.answer_start).replace(/\"/g, "")}</td><td>${JSON.stringify(obj.answer_end).replace(/\"/g, "")}</td><td>${JSON.stringify(obj.compare_start).replace(/\"/g, "")}</td><td>${JSON.stringify(obj.compare_end).replace(/\"/g, "")}</td></tr>`;
        iKey++;
    }

    var iKeyText = iKey.toString() + " active assignments";
    if (iKey ==1){
        iKeyText = iKey.toString() + " active assignment";
    }
    document.getElementById("searchDay").innerHTML = (searchDay);
    document.getElementById("numberOfAssignment").innerHTML = iKeyText;

    // Setting innerHTML as tab variable
    document.getElementById("apiresults").innerHTML = tab;
}

getsearchapi(api_url);
